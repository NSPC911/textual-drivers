from __future__ import annotations

import os
import selectors
from codecs import getincrementaldecoder
from typing import Callable

from textual._loop import loop_last
from textual._parser import ParseError
from textual._xterm_parser import XTermParser
from textual.driver import Driver
from textual.message import Message


def run_linux_input_thread(driver: Driver, on_event: Callable[[Message], None]) -> None:
    """Shared run_input_thread body for Linux drivers.

    Handles the selector loop, pause points, custom handler dispatch, and
    XTerm parser feeding. on_event is called for each parsed event — drivers
    use it to intercept specific event types (e.g. CursorPosition in inline mode).
    """
    selector = selectors.SelectSelector()
    selector.register(driver.fileno, selectors.EVENT_READ)

    fileno = driver.fileno
    EVENT_READ = selectors.EVENT_READ

    parser = XTermParser(driver._debug)
    feed = parser.feed
    tick = parser.tick
    decode = getincrementaldecoder("utf-8")().decode
    read = os.read

    def process_selector_events(
        selector_events: list[tuple[selectors.SelectorKey, int]],
        final: bool = False,
    ) -> None:
        for last, (_, mask) in loop_last(selector_events):
            if mask & EVENT_READ:
                unicode_data = decode(read(fileno, 1024 * 4), final=final and last)
                if not unicode_data:
                    break
                filtered = driver._dispatch_custom_handlers(unicode_data)
                for event in feed(filtered) if filtered else []:
                    on_event(event)
        for event in tick():
            on_event(event)

    try:
        while not driver.exit_event.is_set():
            driver._stdin_pause_point()
            if not driver.exit_event.is_set():
                process_selector_events(selector.select(0.1))
        selector.unregister(driver.fileno)
        process_selector_events(selector.select(0.1), final=True)
    finally:
        selector.close()
        try:
            for _ in feed(""):
                pass
        except (EOFError, ParseError):
            pass
