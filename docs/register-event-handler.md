# register_event_handler

This lets you register custom events that run when specific patterns are detected in the raw stdin data.

## registering the event handler

```py
from textual_drivers import DrivenApp

class MyApp(DrivenApp):
    def on_mount(self) -> None:
        self._driver.register_event_handler(
            pattern,               # see pattern types below
            event_constructor,     # you can pass in the direct type itself
            priority=              # whether to prevent Textual's parser from handling this further
        )
```

## Pattern types

| Pattern                      | Match behaviour                                                                                                       |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `str`                        | [Glob](https://docs.python.org/3/library/fnmatch.html) matched against each ESC-tokenised chunk via `fnmatch.fnmatch` |
| `BoundedPattern(start, end)` | Finds all non-overlapping substrings in the raw data that begin with `start` and end with `end`                       |
| `re.Pattern`                 | Finds all matches of `pattern.finditer(data)` in the raw data                                                         |

## Example

Detect the terminal's response to a Primary Device Attributes query (`\x1b[c`), which arrives as `\x1b[?<params>c`:

```python
from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import Label
from textual_drivers import DrivenApp

class DeviceAttributesReceived(Message):
    def __init__(self, data: str) -> None:
        super().__init__()
        self.data = data

class MyApp(DrivenApp):
    def compose(self) -> ComposeResult:
        yield Label("Waiting for terminal response…")

    def on_mount(self) -> None:
        self.app._driver.register_event_handler("\x1b[?*c", DeviceAttributesReceived)
        self.app._driver.write("\x1b[c")
        self.app._driver.flush()

    def on_device_attributes_received(self, event: DeviceAttributesReceived) -> None:
        self.query_one(Label).update(f"Terminal identified: {event.data!r}")
```

The example above uses a glob pattern. You can also use other pattern types for the same sequence:

**BoundedPattern** (match fixed start and end, ignore middle):
```python
from textual_drivers import BoundedPattern

driver.register_event_handler(
    BoundedPattern(start="\x1b[?1;2", end="c"),
    DeviceAttributesReceived,
    priority=True,
)
```

**re.Pattern** (capture groups via regex):
```python
import re

driver.register_event_handler(
    re.compile(r"\x1b\[\?([0-9;]+)c"),
    DeviceAttributesReceived,
    priority=True,
)
```

## Callable fallback

The `event_constructor` can also be a plain callable that receives the matched string and returns anything:

```python
def _debug(data: str) -> None:
    print(f"raw: {data!r}", flush=True)

driver.register_event_handler(BoundedPattern(start="\x1b]72;", end=_ST), _debug)
```

If a Event is returned from the function/method, it is posted to the app as usual.

## raw_data_signal

`driver.raw_data_signal` is a `Signal[str]` that fires once for every raw stdin read chunk, **before** any pattern matching or filtering. It is the lowest-level observation point available — the string is exactly what came off the file descriptor, decoded from UTF-8 but otherwise unprocessed.

Subscribe in `on_mount` using Textual's signal API:

```python
def on_mount(self) -> None:
    self.app._driver.raw_data_signal.subscribe(self, self._on_raw_stdin)

def _on_raw_stdin(self, data: str) -> None:
    self.query_one("#log", Log).write_line(f"raw: {data!r}")
```
