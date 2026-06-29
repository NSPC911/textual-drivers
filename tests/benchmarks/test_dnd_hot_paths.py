from __future__ import annotations

import asyncio

from pytest_benchmark.fixture import BenchmarkFixture

from textual_drivers._dnd_app import (
    DNDApp,
    DNDDragIn,
    DNDDragOut,
    DNDDragOutOperation,
    DNDDropData,
    Drop,
)
from textual_drivers._mixin import EventHandlerMixin
from textual_drivers._utils import b64decode, b64encode


class RawSignal:
    def publish(self, data: str) -> None:
        pass


class FakeDriver:
    def __init__(self) -> None:
        self.writes: list[str] = []
        self.flush_count = 0

    def write(self, seq: str) -> None:
        self.writes.append(seq)

    def flush(self) -> None:
        self.flush_count += 1


class GlobDriver(EventHandlerMixin):
    def __init__(self) -> None:
        self._event_handlers = []
        self._non_bounded_handlers = []
        self._has_non_bounded_handlers = False
        self._bounded_prefixes = set()
        self.raw_data_signal = RawSignal()  # ty: ignore[invalid-assignment]
        self._app = object()
        self.seen = 0

    def send_message(self, event: object) -> None:
        pass


def make_dnd_app() -> DNDApp:
    app = DNDApp()
    app._driver = FakeDriver()  # ty: ignore[invalid-assignment]
    app._drag_uris = [
        f"file:///tmp/textual-drivers-{index}.txt" for index in range(12)
    ]
    app._drag_op = "copy"
    app._drag_uri_payload = ""
    app._drag_plain_payload = ""
    app.dnd_drag_out_operation = lambda _: DNDDragOutOperation(  # ty: ignore[invalid-assignment]
        app._drag_uris,
        "copy",
        "Drag files",
        3,
    )
    return app


def run_dnd_message_parse_workload() -> int:
    total = 0
    for _ in range(20_000):
        total += DNDDragIn(
            "t=m:x=12:y=34:X=12:Y=34:o=1; text/uri-list text/plain"
        ).pos.x
        total += DNDDragOut("t=o:x=12:y=34").pos.y
        total += DNDDropData("t=r:x=1:m=0;Zm9v").idx
        total += len(
            Drop("t=M:x=12:y=34:X=12:Y=34:o=1; text/uri-list text/plain").mimes
        )
    return total


def run_b64_workload() -> int:
    payload = "\r\n".join(f"file:///tmp/{index}.txt" for index in range(32))
    total = 0
    for _ in range(50_000):
        encoded = b64encode(payload)
        total += len(encoded)
        total += len(b64decode(encoded))
    return total


async def run_drag_out_many() -> int:
    event = DNDDragOut("t=o:x=1:y=2")
    app = make_dnd_app()
    total = 0
    for _ in range(5_000):
        app._driver = FakeDriver()  # ty: ignore[invalid-assignment]
        app.is_dragging_out = False
        await app._on_dnddrag_out(event)
        total += len(app._driver.writes)
        total += app._driver.flush_count
    return total


def run_drag_out_workload() -> int:
    return asyncio.run(run_drag_out_many())


def run_send_drag_data_workload() -> int:
    app = make_dnd_app()
    asyncio.run(app._on_dnddrag_out(DNDDragOut("t=o:x=1:y=2")))
    total = 0
    for index in range(40_000):
        app._send_drag_data(index % 2)
        total += len(app._driver.writes[-1])
    return total


def run_glob_dispatch_workload() -> int:
    driver = GlobDriver()
    driver.register_event_handler("\x1b[<35;*M", lambda _: None)
    chunks = [
        "\x1b[<35;120;44M",
        "\x1b[<35;121;44M",
        "\x1b[<0;80;24m",
        "plain",
    ] * 40_000
    total = 0
    for chunk in chunks:
        total += len(driver._dispatch_custom_handlers(chunk))
    return total


def test_drag_out_batches_adjacent_writes() -> None:
    app = make_dnd_app()

    asyncio.run(app._on_dnddrag_out(DNDDragOut("t=o:x=1:y=2")))

    assert len(app._driver.writes) == 5
    assert app._driver.flush_count == 1


def test_send_drag_data_uses_active_drag_payloads() -> None:
    app = make_dnd_app()
    asyncio.run(app._on_dnddrag_out(DNDDragOut("t=o:x=1:y=2")))
    uri_payload = app._drag_uri_payload
    plain_payload = app._drag_plain_payload
    app._driver = FakeDriver()  # ty: ignore[invalid-assignment]

    app._send_drag_data(0)
    app._send_drag_data(1)

    assert uri_payload in app._driver.writes[0]
    assert plain_payload in app._driver.writes[1]


def test_dnd_message_parse_hot_path(benchmark: BenchmarkFixture) -> None:
    assert benchmark(run_dnd_message_parse_workload) > 0


def test_b64_hot_path(benchmark: BenchmarkFixture) -> None:
    assert benchmark(run_b64_workload) > 0


def test_drag_out_write_hot_path(benchmark: BenchmarkFixture) -> None:
    assert benchmark(run_drag_out_workload) > 0


def test_send_drag_data_hot_path(benchmark: BenchmarkFixture) -> None:
    assert benchmark(run_send_drag_data_workload) > 0


def test_glob_dispatch_hot_path(benchmark: BenchmarkFixture) -> None:
    assert benchmark(run_glob_dispatch_workload) > 0
