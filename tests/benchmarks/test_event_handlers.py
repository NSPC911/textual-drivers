from __future__ import annotations

import re
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
        self._non_bounded_handlers = []
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


def make_mixed_driver(constructor: Any = lambda _: None) -> DummyDriver:
    driver = make_driver(constructor)
    driver.register_event_handler(re.compile(r"mouse:\d+,\d+"), constructor)
    driver.register_event_handler("\x1b[<35;*M", constructor)
    return driver


CHUNKS = [
    "a",
    "hello world",
    "\x1b[A",
    "\x1b[<35;120;44M",
    "\x1b[<35;121;44M",
    "\x1b[<0;80;24m",
] * 20_000

MATCHING_CHUNK = (
    "before"
    "\x1b]72;t=m:x=1:y=2\x1b\\"
    "middle"
    "\x1b]72;t=o:x=3:y=4\x1b\\"
    "after"
    "\x1b]72;t=e:x=4:y=0\x1b\\"
    "tail"
)
MATCHING_CHUNKS = [MATCHING_CHUNK] * 20_000
MIXED_NO_MATCH_CHUNKS = [
    "plain",
    "\x1b[A",
    "mouse",
    "\x1b[<0;10;20m",
] * 20_000
MIXED_MATCHING_CHUNK = (
    "prefix"
    "\x1b]72;t=m:x=1:y=2\x1b\\"
    "mouse:12,34"
    "\x1b[<35;120;44M"
)
MIXED_MATCHING_CHUNKS = [MIXED_MATCHING_CHUNK] * 20_000


def run_workload() -> int:
    driver = make_driver()
    total = 0
    for chunk in CHUNKS:
        total += len(driver._dispatch_custom_handlers(chunk))
    return total


def run_bounded_match_workload() -> int:
    driver = make_driver(DummyMessage)
    total = 0
    for chunk in MATCHING_CHUNKS:
        total += len(driver._dispatch_custom_handlers(chunk))
    return total + len(driver.sent)


def run_mixed_no_match_workload() -> int:
    driver = make_mixed_driver()
    total = 0
    for chunk in MIXED_NO_MATCH_CHUNKS:
        total += len(driver._dispatch_custom_handlers(chunk))
    return total


def run_mixed_match_workload() -> int:
    driver = make_mixed_driver(DummyMessage)
    total = 0
    for chunk in MIXED_MATCHING_CHUNKS:
        total += len(driver._dispatch_custom_handlers(chunk))
    return total + len(driver.sent)


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


def test_mixed_handlers_preserve_order_and_priority_stripping() -> None:
    driver = make_mixed_driver(DummyMessage)

    filtered = driver._dispatch_custom_handlers(MIXED_MATCHING_CHUNK)

    assert filtered == "prefixmouse:12,34\x1b[<35;120;44M"
    assert [event.data for event in driver.sent] == [
        "\x1b]72;t=m:x=1:y=2\x1b\\",
        "mouse:12,34",
        "\x1b[<35;120;44M",
    ]


def test_dispatch_bounded_handlers_without_osc72_matches(
    benchmark: BenchmarkFixture,
) -> None:
    result = benchmark(run_workload)

    assert result > 0


def test_dispatch_bounded_handlers_with_osc72_matches(
    benchmark: BenchmarkFixture,
) -> None:
    result = benchmark(run_bounded_match_workload)

    assert result > 0


def test_dispatch_mixed_handlers_without_matches(
    benchmark: BenchmarkFixture,
) -> None:
    result = benchmark(run_mixed_no_match_workload)

    assert result > 0


def test_dispatch_mixed_handlers_with_matches(
    benchmark: BenchmarkFixture,
) -> None:
    result = benchmark(run_mixed_match_workload)

    assert result > 0
