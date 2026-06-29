from __future__ import annotations

from textual import events
from textual.drivers.linux_inline_driver import LinuxInlineDriver
from textual.message import Message

from textual_drivers._linux_input import run_linux_input_thread
from textual_drivers._mixin import EventHandlerMixin, LockStdinMixin


class CustomLinuxInlineDriver(LockStdinMixin, EventHandlerMixin, LinuxInlineDriver):
    """LinuxInlineDriver with lock_stdin and register_event_handler support."""

    def run_input_thread(self) -> None:
        """Wait for input, honouring lock_stdin() and custom handlers."""

        def on_event(event: Message) -> None:
            if isinstance(event, events.CursorPosition):
                self.cursor_origin = (event.x, event.y)
            else:
                self.process_message(event)

        run_linux_input_thread(self, on_event)
