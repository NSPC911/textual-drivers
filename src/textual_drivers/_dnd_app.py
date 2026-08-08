"""Base app with kitty drag-in and drag-out protocol support."""

from __future__ import annotations

import re
from shlex import split as shplit
from typing import Literal, NamedTuple

from textual import events, on, work
from textual.dom import DOMNode
from textual.geometry import Offset
from textual.message import Message
from textual.messages import ExitApp
from textual.reactive import var
from textual.timer import Timer

from textual_drivers import BoundedPattern, DrivenApp
from textual_drivers._utils import b64encode, safe

_OSC = "\x1b]"
_ST = "\x1b\\"
_DRAG_PAYLOAD_CHUNK_SIZE = 4096
_MAX_PROTOCOL_INTEGER = 2**31 - 1
_MAX_TEXT_SCALE_DENOMINATOR = 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_DRAG_PROGRESS_RE = re.compile(r"t=e:x=(?P<code>\d+)(?::y=(?P<y>-?\d+))?")


def _osc72(meta: str, payload: str | None = None) -> str:
    if payload is None:
        return f"{_OSC}72;{meta}{_ST}"
    return f"{_OSC}72;{meta};{payload}{_ST}"


# -- Internal messages ---------------------------------------------------------


class DNDDragIn(Message):
    """Kitty reports a drag is hovering over the app.
    Handler: on_dnddrag_in (DNDApp internal, calls dnd_drag_in_operation).
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
        self.real_pos: Offset | None = (
            Offset(int(m.group("X")), int(m.group("Y")))
            if m.group("X") and m.group("Y")
            else None
        )
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
        self.real_pos: Offset | None = (
            Offset(int(m.group("X")), int(m.group("Y")))
            if m.group("X") and m.group("Y")
            else None
        )
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


class TextLabel(NamedTuple):
    """Text rendered by the terminal as the drag icon."""

    text: str
    size: float = 1
    """Text scale relative to the terminal's base font size."""
    background_opacity: int = 0
    """Background opacity from 0 (transparent) to 1024 (opaque)."""


class ImageLabel(NamedTuple):
    """Binary image used as the drag icon."""

    data: bytes
    """Raw RGB, RGBA, or PNG data. It is base64 encoded for transmission."""
    width: int
    height: int
    format: Literal["rgb", "rgba", "png"] = "png"


class DNDDragOutOperation(NamedTuple):
    uris: list[str]
    """URIs to offer for dragging out. Must be file://"""
    op: Literal["copy", "move", "either"]
    popup_text: str | None = None
    """Deprecated text label. Prefer label=TextLabel(...)."""
    popup_size: float = 1
    """Deprecated popup_text scale. Prefer TextLabel.size."""
    label: TextLabel | ImageLabel | None = None
    """Text or image to show as the drag icon."""
    extra_mimes: dict[str, bytes] = {}
    """Extra MIME types to offer for dragging out, with their data."""


def _drag_label_sequences(label: TextLabel | ImageLabel) -> list[str]:
    from fractions import Fraction
    from math import isfinite

    if isinstance(label, TextLabel):
        if not (
            type(label.size) in (int, float)
            and isfinite(label.size)
            and label.size >= 0
        ):
            raise ValueError("TextLabel.size must be finite and greater than zero")
        if not isinstance(label.text, str):
            raise TypeError("TextLabel.text must be a string")
        if type(label.background_opacity) is not int:
            raise TypeError("TextLabel.background_opacity must be an integer")
        if not 0 <= label.background_opacity <= 1024:
            raise ValueError("TextLabel.background_opacity must be between 0 and 1024")

        scale = Fraction(str(label.size)).limit_denominator(_MAX_TEXT_SCALE_DENOMINATOR)
        if scale.numerator == 0:
            raise ValueError("TextLabel.size is too small to represent")
        if scale.numerator > _MAX_PROTOCOL_INTEGER:
            raise ValueError("TextLabel.size exceeds the protocol integer range")
        metadata = (
            f"t=p:x=-1:y=0:X={scale.numerator}:Y={scale.denominator}"
            f":o={label.background_opacity}"
        )
        data: str | bytes = label.text
    elif isinstance(label, ImageLabel):
        if not isinstance(label.data, bytes):
            raise TypeError("ImageLabel.data must be bytes")
        if not (type(label.width) is int and type(label.height) is int):
            raise TypeError("ImageLabel dimensions must be integers")
        if label.width <= 0 or label.height <= 0:
            raise ValueError("ImageLabel dimensions must be greater than zero")
        if label.width > _MAX_PROTOCOL_INTEGER or label.height > _MAX_PROTOCOL_INTEGER:
            raise ValueError("ImageLabel dimensions exceed the protocol integer range")
        if label.format not in ("rgb", "rgba", "png"):
            raise ValueError("ImageLabel.format must be 'rgb', 'rgba', or 'png'")
        if label.format == "png":
            if (
                len(label.data) < 24
                or not label.data.startswith(_PNG_SIGNATURE)
                or label.data[8:12] != (13).to_bytes(4, "big")
                or label.data[12:16] != b"IHDR"
            ):
                raise ValueError("ImageLabel PNG data must contain a valid IHDR header")
            png_width = int.from_bytes(label.data[16:20], "big")
            png_height = int.from_bytes(label.data[20:24], "big")
            if (png_width, png_height) != (label.width, label.height):
                raise ValueError("ImageLabel dimensions must match the PNG dimensions")
        else:
            channels = 3 if label.format == "rgb" else 4
            expected_size = label.width * label.height * channels
            if len(label.data) != expected_size:
                raise ValueError(
                    f"ImageLabel {label.format.upper()} data must contain "
                    f"exactly {expected_size} bytes"
                )
        image_format = {"rgb": 24, "rgba": 32, "png": 100}[label.format]
        metadata = f"t=p:x=-1:y={image_format}:X={label.width}:Y={label.height}"
        data = label.data
    else:
        raise TypeError("label must be a TextLabel or ImageLabel")

    encoded = b64encode(data)
    chunks = [
        encoded[index : index + _DRAG_PAYLOAD_CHUNK_SIZE]
        for index in range(0, len(encoded), _DRAG_PAYLOAD_CHUNK_SIZE)
    ] or [""]
    sequences = []
    for index, chunk in enumerate(chunks):
        more = int(index + 1 < len(chunks))
        chunk_metadata = f"{metadata}:m={more}" if index == 0 else f"m={more}"
        sequences.append(_osc72(chunk_metadata, chunk))
    return sequences


class DNDDragInOperation(NamedTuple):
    accepted: bool
    """Whether the drag-in is accepted or rejected."""
    op: Literal["copy", "move", "either"]
    mimes: list[str]
    """List of MIME types to accept for the drag-in."""


# -- App -----------------------------------------------------------------------


class DNDApp(DrivenApp):
    """DrivenApp subclass with kitty drag-in and drag-out support.

    Override dnd_drag_out_operation and dnd_drag_in_operation to customise
    behaviour. Handle Drop, DropData, and DNDDragOutFinished messages for events.
    """

    state: var[Literal["idle", "drag-in", "drag-in-rej", "drag-out"]] = var("idle")

    def _on_mount(self) -> None:
        self._drag_uris: list[str] = []
        self._drag_op: Literal["copy", "move", "either"] = "copy"
        self._current_drop: Drop | None = None
        self._data_chunks: list[str] = []
        self._data_mime_idx: int = 0
        self._close_after_data: bool = False
        self._drop_timeout_timer: Timer | None = None
        self._drop_timeout: float = 30.0
        self._dnd_class_targets: set[DOMNode] = set()

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

    def watch_state(self, state: str) -> None:
        for widget in self._dnd_class_targets:
            widget.update_classes({
                "drag-in-active": state == "drag-in",
                "drag-in-rejected": state == "drag-in-rej",
                "drag-out-active": state == "drag-out",
            })

    # -- Internal handlers -----------------------------------------------------

    async def _on_dnddrag_in(self, event: DNDDragIn) -> None:
        from inspect import isawaitable

        x, y = event.pos
        if x == -1 and y == -1:
            self.state = "idle"
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
            self.state = "drag-in-rej"
            self._write(_osc72("t=m:o=0"))
            return
        self.state = "drag-in"
        # kitty only accepts a concrete operation (1=copy, 2=move) in the
        # t=m reply; anything else is treated as a rejection. For "either",
        # pick whichever operation the drag source actually offers.
        op = result.op
        if op == "either":
            op = "move" if event.op == "move" else "copy"
        op_int = 2 if op == "move" else 1
        self._write(_osc72(f"t=m:o={op_int}", " ".join(result.mimes)))

    async def _on_dnddrag_out(self, event: DNDDragOut) -> None:
        from inspect import isawaitable

        returned = self.dnd_drag_out_operation(event.pos)
        if isawaitable(returned):
            result = await returned
        else:
            result = returned
        if result is None:
            self._write(_osc72("t=E:y=-1"))
            return
        op_int = {"copy": 1, "move": 2, "either": 3}[result.op]
        uri_list = "\r\n".join(result.uris) + "\r\n"
        plain = "\n".join(u.removeprefix("file://") for u in result.uris) + "\n"
        label = result.label or TextLabel(result.popup_text or "", result.popup_size)
        try:
            label_sequences = _drag_label_sequences(label)
        except (TypeError, ValueError):
            self._write(_osc72("t=E:y=-1"))
            raise
        self._drag_uris = result.uris
        self._drag_op = result.op
        self.state = "drag-out"
        self._write(
            _osc72(
                f"t=o:o={op_int}",
                " ".join(("text/uri-list", "text/plain", result.extra_mimes.keys())),
            ),
            _osc72("t=p:x=0", b64encode(uri_list)),
            _osc72("t=p:x=1", b64encode(plain)),
            *[
                _osc72(f"t=p:x={i + 2}", b64encode(data))
                for i, data in enumerate(result.extra_mimes.values())
            ],
            *label_sequences,
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
        import base64

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
            was_active = self.state == "drag-out"
            if was_active:
                self.state = "idle"
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
        self.state = "idle"
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

    def close_dnd(self, op: Literal["copy", "move", "cancel"] | None = None) -> None:
        """Close the current drop session, releasing kitty's drop state.

        op is the concluded operation reported back to the drag source.
        Defaults to the operation of the drop being closed, so a "move"
        drop tells the source to remove the originals.
        """
        if op is None:
            op = self._current_drop.op if self._current_drop is not None else "copy"
        op_int = {"cancel": 0, "copy": 1, "move": 2}[op]
        self._current_drop = None
        self._write(_osc72(f"t=r:o={op_int}"))

    @on(events.Unmount)
    @on(events.Hide)
    @on(ExitApp)
    def stop_kitty(self) -> None:
        self.close_dnd("cancel")
        if self.state == "drag-out":
            self._write(_osc72("t=E:y=-1"))
        self._write(_osc72("t=o:x=2"), _osc72("t=A", ""))

    async def action_quit(self) -> None:
        self.stop_kitty()
        await super().action_quit()

    def add_dnd_class_target(self, widget: DOMNode) -> None:
        self._dnd_class_targets.add(widget)

    def _fatal_error(self) -> None:
        self.stop_kitty()
        return super()._fatal_error()

    def _write(self, *lines: str) -> None:
        for seq in lines:
            self._driver.write(seq)
        self._driver.flush()
