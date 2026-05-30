from __future__ import annotations

import os
import selectors
from codecs import getincrementaldecoder

from textual._loop import loop_last
from textual._parser import ParseError
from textual._xterm_parser import XTermParser
from textual.drivers.linux_driver import LinuxDriver

from textual_drivers._mixin import CustomDriverMixin


class CustomLinuxDriver(CustomDriverMixin, LinuxDriver):
    """LinuxDriver with lock_stdin and register_event_handler support."""

    def run_input_thread(self) -> None:
        """Wait for input, honouring the stdin lock and custom handlers."""
        selector = selectors.SelectSelector()
        selector.register(self.fileno, selectors.EVENT_READ)

        fileno = self.fileno
        EVENT_READ = selectors.EVENT_READ

        parser = XTermParser(self._debug)
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
                    self._dispatch_custom_handlers(unicode_data)
                    for event in feed(unicode_data):
                        self.process_message(event)
            for event in tick():
                self.process_message(event)

        try:
            while not self.exit_event.is_set():
                with self._stdin_lock:
                    process_selector_events(selector.select(0.1))
            selector.unregister(self.fileno)
            process_selector_events(selector.select(0.1), final=True)
        finally:
            selector.close()
            try:
                for _ in feed(""):
                    pass
            except (EOFError, ParseError):
                pass
