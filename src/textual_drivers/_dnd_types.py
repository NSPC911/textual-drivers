"""Messages and value types for kitty drag and drop."""

from __future__ import annotations

import re
from shlex import split as shplit
from typing import Literal, NamedTuple

from textual.geometry import Offset
from textual.message import Message


class Drop(Message):
    """Posted when the user drops content onto the terminal window."""

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
    """Posted once requested MIME data has been received and assembled."""

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


class DropDataError(Message):
    """Posted when Kitty cannot provide requested MIME data."""

    def __init__(
        self, drop_event: Drop, mime: str, error: str, description: str = ""
    ) -> None:
        super().__init__()
        self.drop_event = drop_event
        self.mime = mime
        self.error = error
        self.description = description

    def __repr__(self) -> str:
        return (
            f"DropDataError(drop_event={self.drop_event}, mime={self.mime!r}, "
            f"error={self.error!r}, description={self.description!r})"
        )


class DragOutFinished(Message):
    """Posted when a drag-out operation completes or is cancelled."""

    def __init__(self, cancelled: bool) -> None:
        super().__init__()
        self.cancelled = cancelled

    def __repr__(self) -> str:
        return f"DNDDragOutFinished(cancelled={self.cancelled})"


class TextLabel(NamedTuple):
    """Text rendered by the terminal as the drag icon."""

    text: str
    size: float = 1
    background_opacity: int = 0


class ImageLabel(NamedTuple):
    """Binary image used as the drag icon."""

    data: bytes
    width: int
    height: int
    format: Literal["rgb", "rgba", "png"] = "png"


class DNDDragOutOperation(NamedTuple):
    """Data offered when starting a drag."""

    uris: list[str]
    op: Literal["copy", "move", "either"]
    popup_text: str | None = None
    popup_size: float = 1
    label: TextLabel | ImageLabel | None = None
    extra_mimes: dict[str, bytes] = {}


class DNDDragInOperation(NamedTuple):
    """Decision returned while accepting a drag."""

    accepted: bool
    op: Literal["copy", "move", "either"]
    mimes: list[str]
