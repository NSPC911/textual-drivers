from __future__ import annotations

from textual.drivers.linux_driver import LinuxDriver

from textual_drivers._linux_input import run_linux_input_thread
from textual_drivers._mixin import EventHandlerMixin, LockStdinMixin


class CustomLinuxDriver(LockStdinMixin, EventHandlerMixin, LinuxDriver):
    """LinuxDriver with lock_stdin and register_event_handler support."""

    def run_input_thread(self) -> None:
        """Wait for input, honouring lock_stdin() and custom handlers."""
        run_linux_input_thread(self, self.process_message)
