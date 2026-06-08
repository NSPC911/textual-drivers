"""Base app with kitty drag-in and drag-out protocol support."""

from __future__ import annotations

import base64
from inspect import isawaitable
import re
from typing import Literal, NamedTuple

from textual.message import Message

from textual_drivers import BoundedPattern, DrivenApp
from textual_drivers._utils import b64encode, safe

_OSC = "\x1b]"
_ST = "\x1b\\"


def _osc72(meta: str, payload: str = "") -> str:
    if payload:
        return f"{_OSC}72;{meta};{payload}{_ST}"
    return f"{_OSC}72;{meta}{_ST}"


# -- Internal messages ---------------------------------------------------------


class DNDDragIn(Message):
    """Kitty reports a drag is hovering over the app.

    Handler: on_dnddrag_in (DNDApp internal — calls dnd_drag_in_operation).
    pos is (-1, -1) when the drag leaves the window.
    """

    def __init__(self, data: str) -> None:
        super().__init__()
        m = re.search(
            r"t=m:x=(?P<x>-?\d+):y=(?P<y>-?\d+)"
            r"(?::X=(?P<X>-?\d+):Y=(?P<Y>-?\d+):o=(?P<o>\d+)[^;]*;(?P<mimes>[^\x1b]*))?",
            data,
        )
        if not m:
            raise ValueError(f"Invalid t=m: {data!r}")
        self.pos: tuple[int, int] = (int(m.group("x")), int(m.group("y")))
        o = int(m.group("o")) if m.group("o") else 0
        self.op: Literal["copy", "move", "either"] = (
            "copy" if o == 1 else "move" if o == 2 else "either"
        )
        self.mimes: list[str] = m.group("mimes").split() if m.group("mimes") else []


class DragOut(Message):
    """Kitty reports the user started a drag-out gesture.

    Handler: on_drag_out (DNDApp internal — calls dnd_drag_out_operation).
    """

    def __init__(self, data: str) -> None:
        super().__init__()
        m = re.search(r"t=o:x=(?P<x>-?\d+):y=(?P<y>-?\d+)", data)
        if not m:
            raise ValueError(f"Invalid t=o gesture: {data!r}")
        self.pos: tuple[int, int] = (int(m.group("x")), int(m.group("y")))


class DNDDropData(Message):
    """One t=r data chunk from kitty. Internal — accumulated by on_dnddrop_data."""

    def __init__(self, data: str) -> None:
        super().__init__()
        m = re.search(
            r"t=r:x=(?P<idx>\d+):m=(?P<more>[01]);(?P<b64>[^\x1b]*)",
            data,
        )
        if not m:
            raise ValueError(f"Invalid t=r chunk: {data!r}")
        self.idx: int = int(m.group("idx"))
        self.more: bool = m.group("more") == "1"
        b64 = m.group("b64")
        b64 += "=" * (-len(b64) % 4)
        self.chunk: bytes = base64.b64decode(b64.encode())


# -- User-facing messages ------------------------------------------------------


class Drop(Message):
    """Posted when the user drops content onto the terminal window.

    Call request_data(event, index) from on_drop to fetch the actual content.
    index is 0-based into event.mimes.
    """

    def __init__(self, data: str) -> None:
        super().__init__()
        m = re.search(
            r"t=M:x=(?P<x>\d+):y=(?P<y>\d+):X=(?P<X>\d+):Y=(?P<Y>\d+)"
            r":o=(?P<o>\d+)[^;]*;(?P<mimes>[^\x1b]*)",
            data,
        )
        if not m:
            raise ValueError(f"Invalid t=M: {data!r}")
        self.pos: tuple[int, int] = (int(m.group("x")), int(m.group("y")))
        o = int(m.group("o"))
        self.op: Literal["copy", "move"] = "copy" if o == 1 else "move"
        self.mimes: list[str] = m.group("mimes").split() if m.group("mimes") else []


class DropData(Message):
    """Posted once all requested MIME data has been received and assembled.

    data is list[str] (URI entries) when the requested MIME is text/uri-list,
    bytes for everything else.
    """

    def __init__(self, drop_event: Drop, data: list[str] | bytes) -> None:
        super().__init__()
        self.drop_event = drop_event
        self.data = data


class DragOutFinished(Message):
    """Posted when a drag-out operation fully completes or is cancelled."""

    def __init__(self, cancelled: bool) -> None:
        super().__init__()
        self.cancelled = cancelled


# -- Return Types --------------------------------------------------------------


class DragOutOperation(NamedTuple):
    uris: list[str]
    """URIs to offer for dragging out. Must be file://"""
    op: Literal["copy", "move"]
    popup_text: str
    """Text to show in the drag icon popup. Should be short and descriptive."""
    popup_size: int = 3
    """Size of the popup text. The popup text's size is inversely proportional to this value."""


# -- App -----------------------------------------------------------------------


class DNDApp(DrivenApp):
    """DrivenApp subclass with kitty drag-in and drag-out support.

    Override dnd_drag_out_operation and dnd_drag_in_operation to customise
    behaviour. Handle Drop, DropData, and DragOutFinished messages for events.
    """

    def on_mount(self) -> None:
        self._drag_active: bool = False
        self._drag_uris: list[str] = []
        self._drag_op: Literal["copy", "move"] = "copy"
        self._current_drop: Drop | None = None
        self._data_buf: bytes = b""
        self._data_mime_idx: int = 0
        driver = self._driver
        if not hasattr(driver, "register_event_handler"):
            return
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=m:", end=_ST), safe(DNDDragIn)
        )
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=o:", end=_ST), safe(DragOut)
        )
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=M:", end=_ST), safe(Drop)
        )
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=r:", end=_ST), safe(DNDDropData)
        )
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=e:", end=_ST), self._handle_drag_progress
        )
        self._write(_osc72("t=o:x=1"))
        self._write(_osc72("t=a", "*/*"))

    # -- Internal handlers -----------------------------------------------------

    async def on_dnddrag_in(self, event: DNDDragIn) -> None:
        x, y = event.pos
        if x == -1 and y == -1:
            self._write(_osc72("t=m:o=0"))
            return
        returned = self.dnd_drag_in_operation(event)
        if isawaitable(returned):
            accepted = await returned
        else:
            accepted = returned
        if not accepted:
            self._write(_osc72("t=m:o=0"))
            return
        op_int = 1 if event.op in ("copy", "either") else 2
        self._write(_osc72(f"t=m:o={op_int}", " ".join(event.mimes)))

    async def on_drag_out(self, event: DragOut) -> None:
        returned = self.dnd_drag_out_operation(event.pos)
        if isawaitable(returned):
            result = await returned
        else:
            result = returned
        if result is None:
            self._write(_osc72("t=E:y=-1"))
            return
        self._drag_uris = result.uris
        self._drag_op = result.op
        self._drag_active = True
        op_int = 1 if result.op == "copy" else 2
        self._write(_osc72(f"t=o:o={op_int}", "text/uri-list text/plain"))
        uri_list = "\r\n".join(result.uris) + "\r\n"
        self._write(_osc72("t=p:x=0", b64encode(uri_list)))
        plain = "\n".join(u.removeprefix("file://") for u in result.uris) + "\n"
        self._write(_osc72("t=p:x=1", b64encode(plain)))
        self._write(
            _osc72(
                f"t=p:x=-1:y=0:X={len(result.popup_text)}:Y={result.popup_size}:o=0",
                b64encode(result.popup_text),
            )
        )
        self._write(_osc72("t=P:x=-1"))

    def on_dnddrop_data(self, event: DNDDropData) -> None:
        if event.idx != self._data_mime_idx + 1:  # ignore unrequested MIMEs
            return
        self._data_buf += event.chunk
        if event.more:
            return
        if self._current_drop is None:
            self._data_buf = b""
            return
        mime = self._current_drop.mimes[self._data_mime_idx]
        assembled: list[str] | bytes
        if mime == "text/uri-list":
            assembled = [
                line
                for line in self._data_buf.decode().splitlines()
                if line and not line.startswith("#")
            ]
        else:
            assembled = self._data_buf
        self.post_message(DropData(self._current_drop, assembled))
        self._data_buf = b""
        self._write(_osc72("t=r:o=1"))

    def _handle_drag_progress(self, data: str) -> None:
        m = re.search(r"t=e:x=(?P<code>\d+)(?::y=(?P<y>-?\d+))?", data)
        if not m:
            return
        code = int(m.group("code"))
        if code == 4:
            self._drag_active = False
            self._drag_uris = []
            self.post_message(DragOutFinished(cancelled=m.group("y") == "1"))
        elif code == 5:
            y = m.group("y")
            if y is not None:
                self._send_drag_data(int(y))

    def _send_drag_data(self, idx: int) -> None:
        if idx == 0:
            self._write(
                _osc72("t=e:y=0:m=0", b64encode("\r\n".join(self._drag_uris) + "\r\n"))
            )
        elif idx == 1:
            plain = "\n".join(u.removeprefix("file://") for u in self._drag_uris) + "\n"
            self._write(_osc72("t=e:y=1:m=0", b64encode(plain)))

    # -- User-facing stubs -----------------------------------------------------

    def on_drop(self, event: Drop) -> None: ...

    def on_drag_out_finished(self, event: DragOutFinished) -> None: ...

    # -- User override methods -------------------------------------------------

    def dnd_drag_out_operation(self, pos: tuple[int, int]) -> DragOutOperation | None:
        """Return DragOutOperation to start a drag-out, or None to cancel."""
        return None

    def dnd_drag_in_operation(self, event: DNDDragIn) -> bool:
        """Return True to accept the incoming drag, False to reject."""
        return True

    def request_data(self, event: Drop, index: int) -> None:
        """Request MIME data for a drop. index is 0-based into event.mimes."""
        self._current_drop = event
        self._data_mime_idx = index
        self._data_buf = b""
        self._write(_osc72(f"t=r:x={index + 1}"))

    async def action_quit(self) -> None:
        if self._drag_active:
            self._write(_osc72("t=E:y=-1"))
        self._write(_osc72("t=o:x=2"))
        self._write(_osc72("t=a"))
        await super().action_quit()

    # -- Helpers ---------------------------------------------------------------

    def _write(self, seq: str) -> None:
        self._driver.write(seq)
        self._driver.flush()
