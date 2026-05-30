# textual-drivers

Drop-in subclasses of Textual's built-in terminal drivers that add two features:

- **`lock_stdin`** — a context manager that temporarily pauses the driver's stdin reading thread, letting you perform terminal operations (e.g. spawning a subprocess) without interference.
- **`register_event_handler`** — register a glob pattern against raw stdin; when input matches, a custom `Message` is posted into Textual's event system.

## Installation

```
pip install textual-drivers
```

Or with [uv](https://docs.astral.sh/uv/):

```
uv add textual-drivers
```

## Drivers

| Class | Replaces |
|---|---|
| `textual_drivers.linux_driver.CustomLinuxDriver` | `textual.drivers.linux_driver.LinuxDriver` |
| `textual_drivers.linux_inline_driver.CustomLinuxInlineDriver` | `textual.drivers.linux_inline_driver.LinuxInlineDriver` |
| `textual_drivers.windows_driver.CustomWindowsDriver` | `textual.drivers.windows_driver.WindowsDriver` |
| `textual_drivers.headless_driver.CustomHeadlessDriver` | `textual.drivers.headless_driver.HeadlessDriver` |

## Usage

### Selecting the driver

Pass the driver class to `App.run()`:

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

### `lock_stdin`

Use `with self.app._driver.lock_stdin():` to freeze the driver's stdin thread for the duration of the block. The thread finishes its current read cycle (at most ~100 ms) and then blocks until the context manager exits.

```python
import subprocess
from textual.app import App, ComposeResult
from textual.widgets import Button


class MyApp(App):
    def compose(self) -> ComposeResult:
        yield Button("Run shell command")

    def on_button_pressed(self) -> None:
        self.run_worker(self._run_subprocess, thread=True)

    def _run_subprocess(self) -> None:
        with self.app._driver.lock_stdin():
            # stdin is no longer consumed by Textual during this block
            subprocess.run(["some-interactive-program"])
```

### `register_event_handler`

Register a [glob pattern](https://docs.python.org/3/library/fnmatch.html) matched against each raw decoded stdin chunk. When the pattern matches, `event_constructor(pattern)` is called. If the result is a `textual.message.Message` instance it is posted to the app.

```python
from textual.app import App, ComposeResult
from textual.message import Message
from textual.widgets import Label


class PasteReceived(Message):
    def __init__(self, pattern: str) -> None:
        super().__init__()
        self.pattern = pattern


class MyApp(App):
    def compose(self) -> ComposeResult:
        yield Label("Paste something!")

    def on_mount(self) -> None:
        # Fire PasteReceived whenever a bracketed-paste sequence arrives
        self.app._driver.register_event_handler(
            "\x1b[200~*\x1b[201~",
            PasteReceived,
        )

    def on_paste_received(self, event: PasteReceived) -> None:
        self.notify(f"Matched pattern: {event.pattern!r}")
```

The pattern is matched with `fnmatch.fnmatch` against the raw unicode string that was just read from stdin. Normal Textual parsing continues regardless — the custom event is sent in addition to any built-in events.

### Using the mixin directly

If you have your own driver subclass, mix in `CustomDriverMixin` before the base driver:

```python
from textual_drivers._mixin import CustomDriverMixin
from textual.drivers.linux_driver import LinuxDriver


class MyDriver(CustomDriverMixin, LinuxDriver):
    ...
```

The mixin must appear before the driver class in the MRO so that `__init__` chains correctly via `super()`.

## Notes

- `lock_stdin` on `CustomHeadlessDriver` is a no-op (no stdin thread exists in headless mode).
- `register_event_handler` handlers never fire in headless mode for the same reason.
- `CustomWindowsDriver` is only importable on Windows.
