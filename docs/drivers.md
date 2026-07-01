# Drivers

## Available driver classes

| Class                                                         | Replaces                                                |
| ------------------------------------------------------------- | ------------------------------------------------------- |
| `textual_drivers.linux_driver.CustomLinuxDriver`              | `textual.drivers.linux_driver.LinuxDriver`              |
| `textual_drivers.linux_inline_driver.CustomLinuxInlineDriver` | `textual.drivers.linux_inline_driver.LinuxInlineDriver` |
| `textual_drivers.windows_driver.CustomWindowsDriver`          | `textual.drivers.windows_driver.WindowsDriver`          |
| `textual_drivers.headless_driver.CustomHeadlessDriver`        | `textual.drivers.headless_driver.HeadlessDriver`        |

## DrivenApp

The easiest way to get started is `DrivenApp`, which selects the right driver for the current platform automatically:

```python
from textual_drivers import DrivenApp

class MyApp(DrivenApp):
    ...

MyApp().run()
```

## Manual driver selection

Pass the driver class to `App.run()` or `App.__init__()` directly:

```python
import sys
from textual.app import App, ComposeResult
from textual.widgets import Label

if sys.platform == "win32":
    from textual_drivers.windows_driver import CustomWindowsDriver as Driver
else:
    from textual_drivers.linux_driver import CustomLinuxDriver as Driver


class MyApp(App):
    def compose(self) -> ComposeResult:
        yield Label("Hello!")


MyApp().run(driver_class=Driver)
```

## Using the mixin in your own driver

If you already have a driver subclass, mix in your preferred things **before** the base driver:

```python
from textual_drivers._mixin import LockStdinMixin, EventHandlerMixin
from textual.drivers.linux_driver import LinuxDriver


class MyDriver(LockStdinMixin, EventHandlerMixin, LinuxDriver):
    ...
```

Use this approach if your driver already handles platform-specific logic but needs event hooks or stdin locking features.

The mixin must appear before the driver class in the MRO so that `__init__` chains correctly via `super()`. You must also call `self._stdin_pause_point()` at the start of your input-thread loop for [`lock_stdin`](lock-stdin) to work.

Feel free to contribute extra mixins for other features.

## Headless mode

- `lock_stdin()` on `CustomHeadlessDriver` is an immediate no-op — no stdin thread exists in headless mode.
- `register_event_handler` handlers never fire in headless mode for the same reason.
- `CustomWindowsDriver` is only importable on Windows.
