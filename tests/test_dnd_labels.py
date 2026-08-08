import asyncio
import base64
from types import SimpleNamespace
from typing import Any, Literal, cast

import pytest

from textual_drivers._dnd_app import DNDApp, _drag_label_sequences
from textual_drivers.dnd import DNDDragOutOperation, ImageLabel, TextLabel


def png_header(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
    )


@pytest.mark.parametrize("label", [TextLabel("2 files"), ImageLabel(b"png", 1, 1)])
def test_drag_out_operation_accepts_label(label: TextLabel | ImageLabel) -> None:
    operation = DNDDragOutOperation(["file:///tmp/example"], "copy", label=label)

    assert operation.label is label


def test_drag_out_operation_keeps_legacy_popup_arguments() -> None:
    operation = DNDDragOutOperation(
        ["file:///tmp/example"], "either", "1 item", popup_size=2
    )

    assert operation.popup_text == "1 item"
    assert operation.popup_size == 2
    assert operation.label is None


def test_text_label_sequence() -> None:
    assert _drag_label_sequences(TextLabel("2 files", 2, 1024)) == [
        "\x1b]72;t=p:x=-1:y=0:X=2:Y=1:o=1024:m=0;MiBmaWxlcw==\x1b\\"
    ]


def test_fractional_text_label_size_uses_integer_ratio() -> None:
    assert _drag_label_sequences(TextLabel("text", 1.5)) == [
        "\x1b]72;t=p:x=-1:y=0:X=3:Y=2:o=0:m=0;dGV4dA==\x1b\\"
    ]


@pytest.mark.parametrize(
    ("image_format", "protocol_format"), [("rgb", 24), ("rgba", 32), ("png", 100)]
)
def test_image_label_formats(
    image_format: Literal["rgb", "rgba", "png"], protocol_format: int
) -> None:
    data = (
        png_header(10, 20)
        if image_format == "png"
        else b"x" * 10 * 20 * (3 if image_format == "rgb" else 4)
    )
    label = ImageLabel(data, 10, 20, image_format)

    assert _drag_label_sequences(label) == [
        f"\x1b]72;t=p:x=-1:y={protocol_format}:X=10:Y=20:m=0;"
        f"{base64.b64encode(data).decode()}\x1b\\"
    ]


def test_image_label_payload_is_chunked() -> None:
    sequences = _drag_label_sequences(ImageLabel(b"x" * 3075, 1025, 1, "rgb"))

    assert len(sequences) == 2
    assert sequences[0].startswith("\x1b]72;t=p:x=-1:y=24:X=1025:Y=1:m=1;")
    assert sequences[1] == "\x1b]72;m=0;eHh4\x1b\\"


@pytest.mark.parametrize(
    "label",
    [
        TextLabel("text", 0),
        TextLabel("text", 1e-100),
        TextLabel("text", float("nan")),
        TextLabel("text", background_opacity=1025),
        ImageLabel(b"", 0, 1),
        ImageLabel(b"short", 1, 1, "rgb"),
        ImageLabel(png_header(2, 1), 1, 1),
        ImageLabel(b"", 1, 1, cast(Any, "jpeg")),
    ],
)
def test_invalid_labels_raise(label: TextLabel | ImageLabel) -> None:
    with pytest.raises(ValueError):
        _drag_label_sequences(label)


def test_invalid_drag_label_cancels_without_activating_drag() -> None:
    class FakeApp:
        def __init__(self) -> None:
            self._drag_uris = ["existing"]
            self._drag_op = "move"
            self.state = "idle"
            self.writes: list[tuple[str, ...]] = []

        def dnd_drag_out_operation(self, _pos: object) -> DNDDragOutOperation:
            return DNDDragOutOperation(
                ["file:///tmp/example"], "copy", label=TextLabel("text", 0)
            )

        def _write(self, *sequences: str) -> None:
            self.writes.append(sequences)

    app = FakeApp()

    with pytest.raises(ValueError):
        asyncio.run(
            DNDApp._on_dnddrag_out(
                cast("DNDApp", cast(Any, app)),
                cast(Any, SimpleNamespace(pos=(0, 0))),
            )
        )

    assert app._drag_uris == ["existing"]
    assert app._drag_op == "move"
    assert app.state == "idle"
    assert app.writes == [("\x1b]72;t=E:y=-1\x1b\\",)]
