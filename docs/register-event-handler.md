# register_event_handler

`register_event_handler(pattern, event_constructor, *, priority=False)` binds a pattern against each raw decoded stdin chunk. When the pattern matches, `event_constructor(data)` is called with the matched string. If the result is a `textual.message.Message` instance it is posted to the app.

Normal Textual parsing continues regardless — the custom event fires **in addition** to any built-in events Textual would normally raise.

## priority

Pass `priority=True` to claim exclusive ownership of the matched sequences. Matched data is stripped from the raw input before it is fed to Textual's internal XTermParser and to any non-priority handlers, preventing double-dispatch.

```python
# The OSC 72 sequence is consumed here and will NOT reach XTermParser.
driver.register_event_handler(
    BoundedPattern(start="\x1b]72;t=e:", end=_ST),
    handle_drag_progress,
    priority=True,
)
```

Use `priority=True` whenever the sequence would otherwise be misinterpreted by Textual's key parser (e.g. OSC payload text leaking as key events).

## Pattern types

| Pattern | Match behaviour |
| --- | --- |
| `str` | [Glob](https://docs.python.org/3/library/fnmatch.html) matched against each ESC-tokenised chunk via `fnmatch.fnmatch` |
| `BoundedPattern(start, end)` | Finds all non-overlapping substrings in the raw data that begin with `start` and end with `end` |
| `re.Pattern` | Finds all matches of `pattern.finditer(data)` in the raw data |

## Glob example

Detect the terminal's response to a Primary Device Attributes query (`\x1b[c`), which arrives as `\x1b[?<params>c`:

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

## BoundedPattern example

Match an OSC sequence with a known start prefix and string terminator:

```python
import re
from textual_drivers import BoundedPattern

_OSC = "\x1b]"
_ST  = "\x1b\\"

# Fires for every  ESC ] 72 ; t=o: … ESC \  sequence in the incoming data.
# priority=True strips the sequence so XTermParser never sees it.
driver.register_event_handler(
    BoundedPattern(start=f"{_OSC}72;t=o:", end=_ST),
    DragGestureMsg,
    priority=True,
)
```

`BoundedPattern` is the right choice for OSC / APC / DCS sequences and any other protocol that uses a fixed start sentinel and string terminator, because it correctly handles cases where multiple sequences arrive in a single stdin read.

## re.Pattern example

Match cursor position reports (`\x1b[row;colR`) with a compiled regex:

```python
import re

driver.register_event_handler(
    re.compile(r"\x1b\[(\d+);(\d+)R"),
    CursorPositionMsg,
)
```

## Callable fallback

The `event_constructor` can also be a plain callable that receives the matched string and returns `None` (for side-effects only):

```python
def _debug(data: str) -> None:
    print(f"raw: {data!r}", flush=True)

driver.register_event_handler(BoundedPattern(start="\x1b]72;", end=_ST), _debug)
```

## Message handler naming

Textual derives the handler name from the message class name using `snake_case`:

| Message class | Handler name |
| --- | --- |
| `DeviceAttributesReceived` | `on_device_attributes_received` |
| `BoundedPattern` match → `MyMsg` | `on_my_msg` |

Handler methods on the app (or any widget) are called automatically when the message is posted.

## raw_data_signal

`driver.raw_data_signal` is a `Signal[str]` that fires once for every raw stdin read chunk, **before** any pattern matching or filtering. It is the lowest-level observation point available — the string is exactly what came off the file descriptor, decoded from UTF-8 but otherwise unprocessed.

Subscribe in `on_mount` using Textual's signal API:

```python
def on_mount(self) -> None:
    self.app._driver.raw_data_signal.subscribe(self, self._on_raw_stdin)

def _on_raw_stdin(self, data: str) -> None:
    self.query_one("#log", Log).write_line(f"raw: {data!r}")
```

`subscribe(node, callback)` ties the subscription lifetime to `node` — the callback is automatically removed when the node is unmounted. Pass `immediate=True` to invoke the callback on the stdin thread itself rather than queuing it through Textual's message loop (useful when ordering relative to other events matters, but be careful with thread safety).

`raw_data_signal` fires for **all** stdin data, including mouse motion and key events. Filter aggressively in the callback if it is performance-sensitive.
