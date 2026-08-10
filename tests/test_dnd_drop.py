from types import SimpleNamespace
from typing import Any, cast

import pytest

from textual_drivers._dnd_app import DNDApp, DNDDropData, DropDataError


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
    assembled: list[tuple[list[bytes], str]] = []

    class FakeTimer:
        def stop(self) -> None:
            pass

    class FakeApp:
        _data_mime_idx = 0
        _drop_timeout_timer = FakeTimer()
        _data_chunks: list[bytes] = []
        _data_b64_chunks: list[str] = []
        _current_drop = SimpleNamespace(mimes=["text/plain"])
        _close_after_data = False

        def _assemble_drop(
            self, _drop: object, chunks: list[bytes], mime: str, _close: bool
        ) -> None:
            assembled.append((chunks, mime))

        def _arm_drop_timeout(self) -> None:
            pass

    app = cast("DNDApp", cast(Any, FakeApp()))
    DNDApp._on_dnddrop_data(app, DNDDropData("\x1b]72;t=r:x=1:m=1;YW\x1b\\"))
    DNDApp._on_dnddrop_data(app, DNDDropData("\x1b]72;t=r:x=1:m=0;Jj\x1b\\"))
    DNDApp._on_dnddrop_data(app, DNDDropData("\x1b]72;t=r:x=1:m=0;ZA\x1b\\"))
    assert assembled == []

    DNDApp._on_dnddrop_data(app, DNDDropData("\x1b]72;t=r:x=1\x1b\\"))
    assert assembled == [([b"abc", b"d"], "text/plain")]


@pytest.mark.parametrize(
    ("method", "args", "expected"),
    [
        (
            DNDApp._handle_drop_error,
            ("\x1b]72;t=R:x=1;EIO:failed to read data\x1b\\",),
            ("EIO", "failed to read data"),
        ),
        (
            DNDApp._drop_timed_out,
            (),
            ("ETIMEDOUT", "drop data request timed out"),
        ),
    ],
)
def test_drop_data_error_cancels_drop(
    method: object, args: tuple[str, ...], expected: tuple[str, str]
) -> None:
    drop = SimpleNamespace(mimes=["image/png"])

    class FakeApp:
        _current_drop: SimpleNamespace | None = drop
        _data_mime_idx = 0
        cancelled = False
        posted: list[DropDataError] = []

        def close_dnd(self, op: str) -> None:
            assert op == "cancel"
            self.cancelled = True
            self._current_drop = None

        def post_message(self, message: DropDataError) -> None:
            self.posted.append(message)

    app = cast("DNDApp", cast(Any, FakeApp()))
    if method is DNDApp._drop_timed_out:
        DNDApp._drop_timed_out(app, cast(Any, drop), 0)
    else:
        DNDApp._handle_drop_error(app, args[0])

    assert cast(Any, app).cancelled
    error = cast(Any, app).posted[0]
    assert (error.error, error.description) == expected
    assert error.mime == "image/png"
