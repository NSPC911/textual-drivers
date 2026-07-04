"""Base app with kitty drag-in and drag-out protocol support."""

from __future__ import annotations

import base64
import re
from inspect import isawaitable
from shlex import split as shplit
from typing import Literal, NamedTuple

from textual import events, on, work
from textual.geometry import Offset
from textual.message import Message
from textual.messages import ExitApp
from textual.reactive import var
from textual.timer import Timer

from textual_drivers import BoundedPattern, DrivenApp
from textual_drivers._utils import b64encode, safe

_OSC = "\x1b]"
_ST = "\x1b\\"
_DRAG_PROGRESS_RE = re.compile(r"t=e:x=(?P<code>\d+)(?::y=(?P<y>-?\d+))?")


def _osc72(meta: str, payload: str | None = None) -> str:
    if payload is None:
        return f"{_OSC}72;{meta}{_ST}"
    return f"{_OSC}72;{meta};{payload}{_ST}"


# -- Internal messages ---------------------------------------------------------


class DNDDragIn(Message):
    """Kitty reports a drag is hovering over the app.
    p    Handler: on_dnddrag_in (DNDApp internal - calls dnd_drag_in_operation).
        pos is (-1, -1) when the drag leaves the window.
    """

    re = re.compile(
        r"t=m:x=(?P<x>-?\d+):y=(?P<y>-?\d+)"
        r"(?::X=(?P<X>-?\d+):Y=(?P<Y>-?\d+):o=(?P<o>\d+)[^;]*;(?P<mimes>[^\x1b]*))?"
    )

    def __init__(self, data: str) -> None:
        super().__init__()
        m = self.re.search(data)
        if not m:
            raise ValueError(f"Invalid t=m: {data!r}")
        self.pos: Offset = Offset(int(m.group("x")), int(m.group("y")))
        o = int(m.group("o")) if m.group("o") else 0
        self.op: Literal["copy", "move", "either"] | None = (
            "copy" if o == 1 else "move" if o == 2 else "either"
        )
        self.mimes: list[str] = shplit(m.group("mimes")) if m.group("mimes") else []


class DNDDragOut(Message):
    """Kitty reports the user started a drag-out gesture.

    Handler: on_drag_out (DNDApp internal - calls dnd_drag_out_operation).
    """

    re = re.compile(r"t=o:x=(?P<x>-?\d+):y=(?P<y>-?\d+)")

    def __init__(self, data: str) -> None:
        super().__init__()
        m = self.re.search(data)
        if not m:
            raise ValueError(f"Invalid t=o gesture: {data!r}")
        self.pos: Offset = Offset(int(m.group("x")), int(m.group("y")))

    def __repr__(self) -> str:
        return f"DNDDragOut(pos={self.pos})"


class DNDDropData(Message):
    """One t=r data chunk from kitty. Internal - accumulated by on_dnddrop_data."""

    re = re.compile(r"t=r:x=(?P<idx>\d+):m=(?P<more>[01]);(?P<b64>[^\x1b]*)")

    def __init__(self, data: str) -> None:
        super().__init__()
        m = self.re.search(data)
        if not m:
            raise ValueError(f"Invalid t=r chunk: {data!r}")
        self.idx: int = int(m.group("idx"))
        self.more: bool = m.group("more") == "1"
        self.chunk: str = m.group("b64")

    def __repr__(self) -> str:
        return f"DNDDropData(idx={self.idx}, more={self.more}, chunk_len={len(self.chunk)})"


# -- User-facing messages ------------------------------------------------------


class Drop(Message):
    """Posted when the user drops content onto the terminal window.

    Call request_data(event, index) from on_drop to fetch the actual content.
    index is 0-based into event.mimes. Call close_dnd() when done fetching
    all desired MIMEs to release kitty's drop state.

    Check event.rejected before processing — kitty sends x=-1,y=-1 when the
    drop was previously rejected by dnd_drag_in_operation.
    """

    re = re.compile(
        r"t=M:x=(?P<x>-?\d+):y=(?P<y>-?\d+)"
        r"(?::X=(?P<X>-?\d+):Y=(?P<Y>-?\d+):o=(?P<o>\d+)[^;]*;(?P<mimes>[^\x1b]*))?",
    )

    def __init__(self, data: str) -> None:
        super().__init__()
        m = self.re.search(data)
        if not m:
            raise ValueError(f"Invalid t=M: {data!r}")
        self.pos: Offset = Offset(int(m.group("x")), int(m.group("y")))
        self.rejected: bool = m.group("o") is None
        o = int(m.group("o")) if m.group("o") else 1
        self.op: Literal["copy", "move"] = "copy" if o == 1 else "move"
        self.mimes: list[str] = shplit(m.group("mimes")) if m.group("mimes") else []

    def __repr__(self) -> str:
        return f"Drop(pos={self.pos}, op={self.op}, mimes={self.mimes})"


class DropData(Message):
    """Posted once all requested MIME data has been received and assembled.

    data is list[str] (URI entries) when the requested MIME is text/uri-list,
    bytes for everything else.
    """

    def __init__(self, drop_event: Drop, data: list[str] | bytes, mime: str) -> None:
        super().__init__()
        self.drop_event = drop_event
        self.data = data
        self.mime = mime

    def __repr__(self) -> str:
        data_repr = (
            f"{len(self.data)} bytes"
            if isinstance(self.data, bytes)
            else repr(self.data)
        )
        return f"DropData(drop_event={self.drop_event}, data={data_repr}, mime={self.mime})"


class DragOutFinished(Message):
    """Posted when a drag-out operation fully completes or is cancelled."""

    def __init__(self, cancelled: bool) -> None:
        super().__init__()
        self.cancelled = cancelled

    def __repr__(self) -> str:
        return f"DNDDragOutFinished(cancelled={self.cancelled})"


# -- Return Types --------------------------------------------------------------


class DNDDragOutOperation(NamedTuple):
    uris: list[str]
    """URIs to offer for dragging out. Must be file://"""
    op: Literal["copy", "move"]
    popup_text: str
    """Text to show in the drag icon popup. Should be short and descriptive."""
    popup_size: int = 3
    """Size of the popup text. The popup text's size is inversely proportional to this value."""


class DNDDragInOperation(NamedTuple):
    accepted: bool
    """Whether the drag-in is accepted or rejected."""
    op: Literal["copy", "move", "either"]
    """The operation to allow for the drag-in."""
    mimes: list[str]
    """List of MIME types to accept for the drag-in."""


# -- App -----------------------------------------------------------------------


class DNDApp(DrivenApp):
    """DrivenApp subclass with kitty drag-in and drag-out support.

    Override dnd_drag_out_operation and dnd_drag_in_operation to customise
    behaviour. Handle Drop, DropData, and DNDDragOutFinished messages for events.
    """

    is_dragging_out: var[bool] = var(False, toggle_class="drag-out-active")
    is_dragging_in: var[bool] = var(False, toggle_class="drag-in-active")
    is_drag_in_rej: var[bool] = var(False, toggle_class="drag-in-rejected")

    def _on_mount(self) -> None:
        self._drag_uris: list[str] = []
        self._drag_op: Literal["copy", "move"] = "copy"
        self._current_drop: Drop | None = None
        self._data_chunks: list[str] = []
        self._data_mime_idx: int = 0
        self._close_after_data: bool = False
        self._drop_timeout_timer: Timer | None = None
        self._drop_timeout: float = 30.0

        driver = self._driver
        if not hasattr(driver, "register_event_handler"):
            return
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=m:", end=_ST),
            safe(DNDDragIn),
            priority=True,
        )
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=o:", end=_ST),
            safe(DNDDragOut),
            priority=True,
        )
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=M:", end=_ST),
            Drop,
            priority=True,
        )
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=r:", end=_ST),
            safe(DNDDropData),
            priority=True,
        )
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=e:", end=_ST),
            self._handle_drag_progress,
            priority=True,
        )
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=E:", end=_ST),
            lambda _: None,
            priority=True,
        )
        self._write(_osc72("t=o:x=1"), _osc72("t=a", "*/*"))

    def _set_drag_in(self, accepted: bool | None) -> None:
        self.is_dragging_in = accepted is True
        self.is_drag_in_rej = accepted is False

    # -- Internal handlers -----------------------------------------------------

    async def _on_dnddrag_in(self, event: DNDDragIn) -> None:
        x, y = event.pos
        if x == -1 and y == -1:
            self._set_drag_in(None)
            self._write(_osc72("t=m:o=0"))
            return
        result = self.dnd_drag_in_operation(event)
        if isawaitable(result):
            result = await result
        else:
            result = result
        if isinstance(result, bool):
            result = DNDDragInOperation(accepted=result, op="either", mimes=event.mimes)
        if not result.accepted:
            self._set_drag_in(False)
            self._write(_osc72("t=m:o=0"))
            return
        self._set_drag_in(True)
        op_int = 1 if result.op in ("copy", "either") else 0
        self._write(_osc72(f"t=m:o={op_int}", " ".join(result.mimes)))

    async def _on_dnddrag_out(self, event: DNDDragOut) -> None:
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
        self.is_dragging_out = True
        op_int = 1 if result.op == "copy" else 2
        uri_list = "\r\n".join(result.uris) + "\r\n"
        plain = "\n".join(u.removeprefix("file://") for u in result.uris) + "\n"
        self._write(
            _osc72(f"t=o:o={op_int}", "text/uri-list text/plain"),
            _osc72("t=p:x=0", b64encode(uri_list)),
            _osc72("t=p:x=1", b64encode(plain)),
            _osc72(
                f"t=p:x=-1:y=0:X={len(result.popup_text)}:Y={result.popup_size}:o=0",
                b64encode(result.popup_text),
            ),
            _osc72("t=P:x=-1"),
        )

    def _on_dnddrop_data(self, event: DNDDropData) -> None:
        if event.idx != self._data_mime_idx + 1:  # ignore unrequested MIMEs
            return
        if self._drop_timeout_timer is not None:
            self._drop_timeout_timer.stop()
        self._data_chunks.append(event.chunk)
        if event.more:
            return
        if self._current_drop is None:
            self._data_chunks = []
            return
        self._assemble_drop(
            self._current_drop,
            self._data_chunks,
            self._current_drop.mimes[self._data_mime_idx],
            self._close_after_data,
        )
        self._data_chunks = []

    @work(thread=True)
    def _assemble_drop(
        self,
        drop: Drop,
        chunks: list[str],
        mime: str,
        close: bool,
    ) -> None:
        b64 = "".join(chunks)
        b64 += "=" * (-len(b64) % 4)
        raw = base64.b64decode(b64.encode())
        assembled: list[str] | bytes
        if mime == "text/uri-list":
            assembled = [
                line
                for line in raw.decode().splitlines()
                if line and not line.startswith("#")
            ]
        else:
            assembled = raw
        self.post_message(DropData(drop, assembled, mime))
        if close:
            self.call_from_thread(self.close_dnd)

    def _handle_drag_progress(self, data: str) -> None:
        m = _DRAG_PROGRESS_RE.search(data)
        if not m:
            return
        code = m.group("code")
        if code == "4":
            was_active = self.is_dragging_out
            self.is_dragging_out = False
            self._drag_uris = []
            self._write(_osc72("t=o:x=1"))
            if was_active:
                self.post_message(DragOutFinished(cancelled=m.group("y") == "1"))
        elif code == "5":
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

    async def on_drop(self, event: Drop) -> None:
        self.is_dragging_out = False
        self._set_drag_in(None)
        if event.rejected:
            event.stop().prevent_default()

    # async def on_drag_out_finished(self, event: DragOutFinished) -> None: ...

    # async def on_drop_data(self, event: DropData) -> None: ...

    # -- User override methods -------------------------------------------------

    async def dnd_drag_out_operation(self, pos: Offset) -> DNDDragOutOperation | None:
        """Return DNDDragOutOperation to start a drag-out, or None to cancel."""  # noqa: DOC201
        return None

    async def dnd_drag_in_operation(
        self, event: DNDDragIn
    ) -> DNDDragInOperation | bool:
        """Return True to accept the incoming drag, False to reject."""  # noqa: DOC201
        return DNDDragInOperation(accepted=True, op="either", mimes=event.mimes)

    # -- Helpers ---------------------------------------------------------------

    def request_data(self, event: Drop, index: int, close: bool = True) -> None:
        """Request MIME data for a drop. index is 0-based into event.mimes.

        If close=True, the drop session is closed automatically once the data
        arrives. Otherwise call close_dnd() explicitly when done.
        """
        self._current_drop = event
        self._data_mime_idx = index
        self._data_chunks = []
        self._drop_timeout_timer = self.set_timer(
            self._drop_timeout,
            lambda: self.post_message(DropData(event, b"", event.mimes[index])),
            name="kitty dnd drop request timeout timer",
        )
        self._close_after_data = close
        self._write(_osc72(f"t=r:x={index + 1}"))

    def close_dnd(self) -> None:
        """Close the current drop session, releasing kitty's drop state."""
        self._write(_osc72("t=r:o=1"))

    @on(events.Unmount)
    @on(events.Hide)
    @on(ExitApp)
    def stop_kitty(self) -> None:
        self.close_dnd()
        if self.is_dragging_out:
            self._write(_osc72("t=E:y=-1"))
        self._write(_osc72("t=o:x=2"), _osc72("t=A", ""))

    async def action_quit(self) -> None:
        self.stop_kitty()
        await super().action_quit()

    def _fatal_error(self) -> None:
        self.stop_kitty()
        return super()._fatal_error()

    def _write(self, *lines: str) -> None:
        for seq in lines:
            self._driver.write(seq)
        self._driver.flush()
