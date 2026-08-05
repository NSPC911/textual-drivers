from typing import Literal

import pytest

from textual_drivers._dnd_app import _drag_label_sequences
from textual_drivers.dnd import DNDDragOutOperation, ImageLabel, TextLabel


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


@pytest.mark.parametrize(
    ("image_format", "protocol_format"), [("rgb", 24), ("rgba", 32), ("png", 100)]
)
def test_image_label_formats(
    image_format: Literal["rgb", "rgba", "png"], protocol_format: int
) -> None:
    label = ImageLabel(b"image", 10, 20, image_format)

    assert _drag_label_sequences(label) == [
        f"\x1b]72;t=p:x=-1:y={protocol_format}:X=10:Y=20:m=0;aW1hZ2U=\x1b\\"
    ]


def test_image_label_payload_is_chunked() -> None:
    sequences = _drag_label_sequences(ImageLabel(b"x" * 3073, 1, 1))

    assert len(sequences) == 2
    assert sequences[0].startswith("\x1b]72;t=p:x=-1:y=100:X=1:Y=1:m=1;")
    assert sequences[1] == "\x1b]72;m=0;eA==\x1b\\"


@pytest.mark.parametrize(
    "label",
    [
        TextLabel("text", 0),
        TextLabel("text", background_opacity=1025),
        ImageLabel(b"", 0, 1),
    ],
)
def test_invalid_label_dimensions_raise(label: TextLabel | ImageLabel) -> None:
    with pytest.raises(ValueError):
        _drag_label_sequences(label)
