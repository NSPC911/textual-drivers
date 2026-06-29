from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from textual.drivers.headless_driver import HeadlessDriver

from textual_drivers._mixin import EventHandlerMixin, LockStdinMixin


class CustomHeadlessDriver(LockStdinMixin, EventHandlerMixin, HeadlessDriver):
    """HeadlessDriver with lock_stdin and register_event_handler support.

    lock_stdin is a true no-op here — there is no stdin input thread to pause.
    register_event_handler handlers never fire because no stdin is read.
    Useful for testing code that references the driver API.
    """

    @contextmanager
    def lock_stdin(self) -> Generator[None, None, None]:
        """No-op: headless driver has no stdin thread to pause."""
        yield
