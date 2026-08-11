"""Kitty drag-and-drop wire protocol handling."""

from __future__ import annotations

import base64
import re
import tempfile
import threading
import time
from fractions import Fraction
from math import isfinite
from shlex import split as shplit
from typing import Literal

from textual.geometry import Offset
from textual.message import Message

from textual_drivers._dnd_types import ImageLabel, TextLabel
from textual_drivers._utils import b64encode

ST = "\x1b\\"
DRAG_PROGRESS_RE = re.compile(r"t=e:x=(?P<code>\d+)(?::y=(?P<y>-?\d+))?")
DROP_ERROR_RE = re.compile(
    r"t=R:(?P<meta>[^;\x1b]*);(?P<error>[^:;\x1b]+)(?::(?P<description>[^\x1b]*))?"
)

_DRAG_PAYLOAD_CHUNK_SIZE = 4096
_MAX_PROTOCOL_INTEGER = 2**31 - 1
_MAX_TEXT_SCALE_DENOMINATOR = 1024
_DROP_MEMORY_LIMIT = 8 * 1024 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def osc72(meta: str, payload: str | None = None) -> str:
    if payload is None:
        return f"\x1b]72;{meta}{ST}"
    return f"\x1b]72;{meta};{payload}{ST}"


class DNDDragIn(Message):
    """Kitty reports a drag hovering over the app."""

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
    """Kitty reports the user started a drag-out gesture."""

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
    """One dropped-data frame from Kitty."""

    re = re.compile(r"t=r:(?P<meta>[^;\x1b]*)(?:;(?P<b64>[^\x1b]*))?")

    def __init__(self, data: str) -> None:
        super().__init__()
        m = self.re.search(data)
        if not m:
            raise ValueError(f"Invalid t=r chunk: {data!r}")
        meta = dict(
            part.split("=", 1) for part in m.group("meta").split(":") if "=" in part
        )
        if "x" not in meta or meta.get("m", "0") not in {"0", "1"}:
            raise ValueError(f"Invalid t=r chunk: {data!r}")
        self.idx = int(meta["x"])
        self.more = meta.get("m", "0") == "1"
        self.chunk = m.group("b64") or ""

    def __repr__(self) -> str:
        return f"DNDDropData(idx={self.idx}, more={self.more}, chunk_len={len(self.chunk)})"


class DNDDropDataComplete(Message):
    """A fully received MIME stream."""

    def __init__(self, idx: int, data: tempfile.SpooledTemporaryFile[bytes]) -> None:
        super().__init__()
        self.idx = idx
        self.data = data


class DNDDropDataFailed(Message):
    """A MIME stream that could not be decoded."""

    def __init__(self, idx: int, description: str) -> None:
        super().__init__()
        self.idx = idx
        self.description = description


class DropDataReceiver:
    """Decode and spool DnD data on the terminal input thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._idx = 0
        self._b64_chunks: list[str] = []
        self._data: tempfile.SpooledTemporaryFile[bytes] | None = None
        self._last_activity = 0.0

    def reset(self, idx: int) -> None:
        with self._lock:
            if self._data is not None:
                self._data.close()
            self._idx = idx
            self._b64_chunks = []
            self._data = tempfile.SpooledTemporaryFile(  # noqa: SIM115
                max_size=_DROP_MEMORY_LIMIT
            )
            self._last_activity = time.monotonic()

    def cancel(self) -> None:
        with self._lock:
            if self._data is not None:
                self._data.close()
            self._data = None
            self._b64_chunks = []

    def idle_for(self) -> float:
        with self._lock:
            return time.monotonic() - self._last_activity

    def __call__(self, data: str) -> Message | None:
        try:
            event = DNDDropData(data)
        except ValueError:
            return None
        with self._lock:
            if self._data is None or event.idx != self._idx:
                return None
            self._last_activity = time.monotonic()
            if event.chunk:
                self._b64_chunks.append(event.chunk)
            if event.more:
                return None
            if self._b64_chunks:
                encoded = "".join(self._b64_chunks)
                self._b64_chunks = []
                try:
                    self._data.write(
                        base64.b64decode(encoded + "=" * (-len(encoded) % 4))
                    )
                except ValueError as error:
                    self._data.close()
                    self._data = None
                    return DNDDropDataFailed(event.idx, str(error))
                return None
            result = self._data
            result.seek(0)
            self._data = None
            return DNDDropDataComplete(event.idx, result)


def drag_payload_sequences(metadata: str, data: str | bytes) -> list[str]:
    encoded = b64encode(data)
    chunks = [
        encoded[index : index + _DRAG_PAYLOAD_CHUNK_SIZE]
        for index in range(0, len(encoded), _DRAG_PAYLOAD_CHUNK_SIZE)
    ] or [""]
    return [
        osc72(
            f"{metadata}:m={int(index + 1 < len(chunks))}"
            if index == 0
            else f"m={int(index + 1 < len(chunks))}",
            chunk,
        )
        for index, chunk in enumerate(chunks)
    ]


def drag_label_sequences(label: TextLabel | ImageLabel) -> list[str]:
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
    return drag_payload_sequences(metadata, data)
