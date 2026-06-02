from __future__ import annotations

from textual.app import App
from textual.types import CSSPathType

from textual_drivers._mixin import CustomDriverMixin, EventHandlerMixin, LockStdinMixin
from textual_drivers.headless_driver import CustomHeadlessDriver


class DrivenApp(App):
    def __init__(self, css_path: CSSPathType | None = None, watch_css: bool = False, ansi_color: bool | None = None) -> None:
        import sys
        if sys.platform == "win32":
            from textual_drivers.windows_driver import CustomWindowsDriver as _Driver
        else:
            from textual_drivers.linux_driver import CustomLinuxDriver as _Driver
        super().__init__(driver_class=_Driver, css_path=css_path, watch_css=watch_css, ansi_color=ansi_color)


__all__ = [
    "DrivenApp",
    "CustomDriverMixin",
    "EventHandlerMixin",
    "LockStdinMixin",
    "CustomHeadlessDriver",
]
