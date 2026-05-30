from __future__ import annotations

from textual.drivers.headless_driver import HeadlessDriver

from textual_drivers._mixin import CustomDriverMixin


class CustomHeadlessDriver(CustomDriverMixin, HeadlessDriver):
    """HeadlessDriver with lock_stdin and register_event_handler support.

    lock_stdin is a no-op here (no real stdin thread), and custom handlers
    never fire (no stdin is read). Useful for testing code that references
    the driver API.
    """
