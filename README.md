# textual-drivers

Drop-in subclasses of Textual's built-in terminal drivers that add two features:

- **`lock_stdin`** — a context manager that pauses the driver's stdin reading thread and waits for it to confirm the pause before yielding, letting you run terminal operations (e.g. spawning a subprocess) without interference.
- **`register_event_handler`** — register a pattern against raw stdin; when input matches, a custom `Message` is posted into Textual's event system. Patterns can be a glob string, a `BoundedPattern(start, end)` for sequences with known delimiters, or a compiled `re.Pattern`.

## Installation

```
uv add textual-drivers
```

## Drivers

| Class                                                         | Replaces                                                |
| ------------------------------------------------------------- | ------------------------------------------------------- |
| `textual_drivers.linux_driver.CustomLinuxDriver`              | `textual.drivers.linux_driver.LinuxDriver`              |
| `textual_drivers.linux_inline_driver.CustomLinuxInlineDriver` | `textual.drivers.linux_inline_driver.LinuxInlineDriver` |
| `textual_drivers.windows_driver.CustomWindowsDriver`          | `textual.drivers.windows_driver.WindowsDriver`          |
| `textual_drivers.headless_driver.CustomHeadlessDriver`        | `textual.drivers.headless_driver.HeadlessDriver`        |

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

Use `with self.app._driver.lock_stdin():` to take exclusive ownership of stdin for the duration of the block. On entry it:

1. Pauses the driver's stdin reader thread (cooperative pause via `threading.Condition`, ≤ ~100 ms to acknowledge).
2. Disables all terminal event reporting that Textual enables: mouse, focus tracking, kitty key protocol, and bracketed paste — so no unsolicited escape sequences can arrive while you hold the lock.
3. Waits 50 ms for any already-in-transit events to land in the OS buffer before yielding, so a `_drain` call at the top of the block reliably clears them.

On exit, event reporting is re-enabled and the input thread resumes. Nesting is supported; the disable/re-enable only happens on the outermost entry and exit.

> **Note:** Plain key events cannot be disabled via escape sequences. Drain stdin at the start of the block to discard any buffered keypresses, then send your query — the terminal response arrives in < 1 ms, before the user can type another character.

> **Note:** `lock_stdin()` pauses Textual's stdin reader and silences terminal events, but does not restore the terminal to cooked/canonical mode. If your subprocess needs line-buffered input (e.g. `input()` or a shell), call `suspend_application_mode()` instead.

```python
import os
import select
import subprocess
import sys
from textual.app import App, ComposeResult
from textual.widgets import Button


class MyApp(App):
    def compose(self) -> ComposeResult:
        yield Button("Query terminal")

    def on_button_pressed(self) -> None:
        self.run_worker(self._query, thread=True)

    def _query(self) -> None:
        fd = sys.stdin.fileno()
        with self.app._driver.lock_stdin():
            # Drain buffered keypresses, then read the terminal's response directly.
            while select.select([fd], [], [], 0)[0]:
                os.read(fd, 4096)
            self.app._driver.write("\x1b[c")   # Primary Device Attributes query
            self.app._driver.flush()
            # Read until the response terminator 'c' arrives (< 1 ms round trip).
            buf = b""
            while b"c" not in buf:
                buf += os.read(fd, 4096)
```

### `register_event_handler`

Register a pattern against each raw decoded stdin chunk. When the pattern matches, `event_constructor(data)` is called with the matched string. If the result is a `textual.message.Message` instance it is posted to the app.

Three pattern types are supported:

| Pattern | Match behaviour |
| ------- | --------------- |
| `str` | [Glob](https://docs.python.org/3/library/fnmatch.html) matched against each ESC-tokenised chunk via `fnmatch.fnmatch` |
| `BoundedPattern(start, end)` | Finds all non-overlapping substrings in the raw data that begin with `start` and end with `end` |
| `re.Pattern` | Finds all matches of `pattern.finditer(data)` in the raw data |

Normal Textual parsing continues regardless — the custom event fires in addition to any built-in events Textual would normally raise.

**Glob example** — detect the terminal's response to a Primary Device Attributes query (`\x1b[c`), which arrives as `\x1b[?<params>c`:

```python
from textual.app import App, ComposeResult
from textual.message import Message
from textual.widgets import Label


class DeviceAttributesReceived(Message):
    def __init__(self, data: str) -> None:
        super().__init__()
        self.data = data


class MyApp(App):
    def compose(self) -> ComposeResult:
        yield Label("Waiting for terminal response…")

    def on_mount(self) -> None:
        self.app._driver.register_event_handler("\x1b[?*c", DeviceAttributesReceived)
        self.app._driver.write("\x1b[c")
        self.app._driver.flush()

    def on_device_attributes_received(self, event: DeviceAttributesReceived) -> None:
        self.query_one(Label).update(f"Terminal identified: {event.data!r}")
```

**`BoundedPattern` example** — match an OSC sequence with a known start prefix and string terminator:

```python
import re
from textual_drivers import BoundedPattern

_OSC = "\x1b]"
_ST  = "\x1b\\"

# Fires for every  ESC ] 72 ; t=o: … ESC \  sequence in the incoming data.
driver.register_event_handler(
    BoundedPattern(start=f"{_OSC}72;t=o:", end=_ST),
    DragGestureMsg,
)
```

**`re.Pattern` example** — match cursor position reports (`\x1b[row;colR`) with a compiled regex:

```python
import re

driver.register_event_handler(
    re.compile(r"\x1b\[(\d+);(\d+)R"),
    CursorPositionMsg,
)
```

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
