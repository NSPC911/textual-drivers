from __future__ import annotations

from textual.app import App
from textual.types import CSSPathType
from textual.widget import Widget

from textual_drivers._mixin import (
    BoundedPattern,
    EventHandlerMixin,
    LockStdinMixin,
    Pattern,
)
from textual_drivers.headless_driver import CustomHeadlessDriver


class DrivenApp(App):
    def __init__(
        self,
        css_path: CSSPathType | None = None,
        watch_css: bool = False,
        ansi_color: bool | None = None,
    ) -> None:
        import sys

        if sys.platform == "win32":
            from textual_drivers.windows_driver import CustomWindowsDriver as _Driver
        else:
            from textual_drivers.linux_driver import CustomLinuxDriver as _Driver
        super().__init__(
            driver_class=_Driver,
            css_path=css_path,
            watch_css=watch_css,
            ansi_color=ansi_color,
        )
        self._driver: _Driver

    def _set_mouse_over(
        self, widget: Widget | None, hover_widget: Widget | None
    ) -> None:
        # Fixes regression in Textual, take a look at POC in
        # https://github.com/NSPC911/textual-trials/blob/master/lagging-mouse.py
        if widget is self.mouse_over and hover_widget is self.hover_over:
            return
        super()._set_mouse_over(widget, hover_widget)


__all__ = [
    "DrivenApp",
    "BoundedPattern",
    "Pattern",
    "EventHandlerMixin",
    "LockStdinMixin",
    "CustomHeadlessDriver",
]
