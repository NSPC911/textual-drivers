from types import SimpleNamespace
from typing import Any, cast

import pytest

from textual_drivers._dnd_app import (
    DNDApp,
    DNDDropData,
    DNDDropDataComplete,
    DropDataError,
    _DropDataReceiver,
)


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


def test_drop_data_is_spooled_until_empty_frame() -> None:
    receiver = _DropDataReceiver()
    receiver.reset(1)

    assert receiver("\x1b]72;t=r:x=1:m=1;YW\x1b\\") is None
    assert receiver("\x1b]72;t=r:x=1:m=0;Jj\x1b\\") is None
    assert receiver("\x1b]72;t=r:x=1:m=0;ZA\x1b\\") is None

    complete = receiver("\x1b]72;t=r:x=1\x1b\\")
    assert isinstance(complete, DNDDropDataComplete)
    with complete.data:
        assert complete.data.read() == b"abcd"


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
        _drop_timeout = 30.0
        cancelled = False
        posted: list[DropDataError] = []
        _drop_receiver = SimpleNamespace(idle_for=lambda: 31.0)

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
