from __future__ import annotations

from typing import Any

from pytest_benchmark.fixture import BenchmarkFixture
from textual.message import Message

from textual_drivers._mixin import BoundedPattern, EventHandlerMixin


class RawSignal:
    def publish(self, data: str) -> None:
        pass


class DummyMessage(Message):
    def __init__(self, data: str) -> None:
        super().__init__()
        self.data = data


class DummyDriver(EventHandlerMixin):
    def __init__(self) -> None:
        self._event_handlers = []
        self._has_non_bounded_handlers = False
        self._bounded_prefixes = set()
        self.raw_data_signal = RawSignal()  # ty: ignore[invalid-assignment]
        self._app = object()
        self.sent: list[DummyMessage] = []

    def send_message(self, event: DummyMessage) -> None:
        self.sent.append(event)


def make_driver(constructor: Any = lambda _: None) -> DummyDriver:
    driver = DummyDriver()
    st = "\x1b\\"
    for tag in ("m", "o", "M", "r", "e", "E"):
        driver.register_event_handler(
            BoundedPattern(start=f"\x1b]72;t={tag}:", end=st),
            constructor,
            priority=True,
        )
    return driver


CHUNKS = [
    "a",
    "hello world",
    "\x1b[A",
    "\x1b[<35;120;44M",
    "\x1b[<35;121;44M",
    "\x1b[<0;80;24m",
] * 20_000


def run_workload() -> int:
    driver = make_driver()
    total = 0
    for chunk in CHUNKS:
        total += len(driver._dispatch_custom_handlers(chunk))
    return total


def test_bounded_handler_priority_stripping() -> None:
    driver = DummyDriver()
    driver.register_event_handler(
        BoundedPattern("<", ">"),
        DummyMessage,
        priority=True,
    )

    assert driver._dispatch_custom_handlers("a<one>b<two>c") == "abc"
    assert [event.data for event in driver.sent] == ["<one>", "<two>"]


def test_bounded_handler_non_match_preserves_data() -> None:
    driver = make_driver(DummyMessage)

    assert driver._dispatch_custom_handlers("plain input") == "plain input"
    assert driver.sent == []


def test_dispatch_bounded_handlers_without_osc72_matches(
    benchmark: BenchmarkFixture,
) -> None:
    result = benchmark(run_workload)

    assert result > 0
