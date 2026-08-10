from types import SimpleNamespace
from typing import Any, cast

import pytest

from textual_drivers._dnd_app import DNDApp, DNDDropData


@pytest.mark.parametrize(
    ("sequence", "expected"),
    [
        ("\x1b]72;t=r:x=1:m=0;YWJj\x1b\\", (1, False, "YWJj")),
        ("\x1b]72;t=r:x=1\x1b\\", (1, False, "")),
        ("\x1b]72;t=r:X=1:x=2:m=1;YWJj\x1b\\", (2, True, "YWJj")),
    ],
)
def test_drop_data_parsing(sequence: str, expected: tuple[int, bool, str]) -> None:
    event = DNDDropData(sequence)

    assert (event.idx, event.more, event.chunk) == expected


def test_drop_data_finishes_only_on_empty_frame() -> None:
    assembled: list[tuple[list[str], str]] = []

    class FakeTimer:
        def stop(self) -> None:
            pass

    class FakeApp:
        _data_mime_idx = 0
        _drop_timeout_timer = FakeTimer()
        _data_chunks: list[str] = []
        _current_drop = SimpleNamespace(mimes=["text/plain"])
        _close_after_data = False

        def _assemble_drop(
            self, _drop: object, chunks: list[str], mime: str, _close: bool
        ) -> None:
            assembled.append((chunks, mime))

    app = cast("DNDApp", cast(Any, FakeApp()))
    DNDApp._on_dnddrop_data(app, DNDDropData("\x1b]72;t=r:x=1:m=0;YWJj\x1b\\"))
    assert assembled == []

    DNDApp._on_dnddrop_data(app, DNDDropData("\x1b]72;t=r:x=1\x1b\\"))
    assert assembled == [(["YWJj"], "text/plain")]
