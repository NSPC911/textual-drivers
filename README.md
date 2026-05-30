# textual-drivers

Drop-in subclasses of Textual's built-in terminal drivers that add two features:

- **`lock_stdin`** — a context manager that pauses the driver's stdin reading thread and waits for it to confirm the pause before yielding, letting you run terminal operations (e.g. spawning a subprocess) without interference.
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

Use `with self.app._driver.lock_stdin():` to freeze the driver's stdin thread for the duration of the block. The implementation uses a `threading.Condition`: the input thread voluntarily stops at its next pause point (at most one read cycle, ≤ ~100 ms), sets an acknowledged flag, and then waits. Only after that acknowledgement does `lock_stdin()` yield — so there is no race between your code and the driver consuming stdin.

```python
import subprocess
from textual.app import App, ComposeResult
from textual.widgets import Button


class MyApp(App):
    def compose(self) -> ComposeResult:
        yield Button("Open editor")

    def on_button_pressed(self) -> None:
        # run_worker(thread=True) runs on a background thread, where blocking is fine
        self.run_worker(self._open_editor, thread=True)

    def _open_editor(self) -> None:
        with self.app._driver.lock_stdin():
            # The input thread is confirmed paused before this line runs.
            # stdin is free for the subprocess to use.
            subprocess.run(["vim", "/tmp/note.txt"])
```

> **Note:** `lock_stdin()` only pauses Textual's stdin reader — it does not restore the terminal to cooked/canonical mode. If your subprocess needs line-buffered input (e.g. `input()` or a shell), call `suspend_application_mode()` instead, which also restores terminal settings.

### `register_event_handler`

Register a [glob pattern](https://docs.python.org/3/library/fnmatch.html) matched against each raw decoded stdin chunk. When the pattern matches, `event_constructor(pattern)` is called. If the result is a `textual.message.Message` instance it is posted to the app.

The example below detects the terminal's response to a Primary Device Attributes query (`\x1b[c`), which arrives as `\x1b[?<params>c`. Textual does not consume this sequence, so it arrives as a raw stdin chunk.

```python
from textual.app import App, ComposeResult
from textual.message import Message
from textual.widgets import Label


class DeviceAttributesReceived(Message):
    def __init__(self, pattern: str) -> None:
        super().__init__()
        self.pattern = pattern


class MyApp(App):
    def compose(self) -> ComposeResult:
        yield Label("Waiting for terminal response…")

    def on_mount(self) -> None:
        # Match the CSI ? … c response to a Primary Device Attributes query.
        self.app._driver.register_event_handler(
            "\x1b[?*c",
            DeviceAttributesReceived,
        )
        # Send the query; the response lands back as a stdin chunk.
        self.app._driver.write("\x1b[c")
        self.app._driver.flush()

    def on_device_attributes_received(
        self, event: DeviceAttributesReceived
    ) -> None:
        self.query_one(Label).update(
            f"Terminal identified — matched pattern: {event.pattern!r}"
        )
```

The pattern is matched with `fnmatch.fnmatch` against the raw unicode string that was just read from stdin. Normal Textual parsing continues regardless — the custom event is sent in addition to any built-in events Textual would normally fire.

### Using the mixin directly

If you have your own driver subclass, mix in `CustomDriverMixin` before the base driver:

```python
from textual_drivers._mixin import CustomDriverMixin
from textual.drivers.linux_driver import LinuxDriver


class MyDriver(CustomDriverMixin, LinuxDriver):
    ...
```

The mixin must appear before the driver class in the MRO so that `__init__` chains correctly via `super()`. You must also call `self._stdin_pause_point()` at the start of your input-thread loop for `lock_stdin()` to work.

## Notes

- `lock_stdin()` waits up to 0.5 s for the input thread to acknowledge the pause. If called before the input thread starts (or after it stops) it proceeds immediately.
- `lock_stdin` on `CustomHeadlessDriver` is an immediate no-op (no stdin thread exists in headless mode).
- `register_event_handler` handlers never fire in headless mode for the same reason.
- `CustomWindowsDriver` is only importable on Windows.
