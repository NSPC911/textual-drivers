# textual-drivers

Drop-in subclasses of Textual's built-in terminal drivers with two extra capabilities:

| Capability | Summary |
| --- | --- |
| [`lock_stdin`](lock-stdin) | Pause the driver's stdin thread and silence terminal events, letting you run terminal queries or subprocesses without interference |
| [`register_event_handler`](register-event-handler) | Bind a pattern against raw stdin; when it matches, a `Message` is posted into Textual's event system |

A higher-level [`DNDApp`](dnd) base class builds on these to implement the full kitty drag-and-drop protocol (drag-in and drag-out).

## Installation

```
uv add textual-drivers
```

Or with pip:

```
pip install textual-drivers
```

## Quick start

```python
import sys
from textual.app import App, ComposeResult
from textual.widgets import Label
from textual_drivers import DrivenApp

class MyApp(DrivenApp):
    def compose(self) -> ComposeResult:
        yield Label("Hello!")

MyApp().run()
```

`DrivenApp` picks the right platform driver automatically. See [Drivers](drivers) for manual driver selection and mixin usage.

## Pages

- [Drivers](drivers): driver classes, `DrivenApp`, and using the mixin in your own driver
- [lock-stdin](lock-stdin): exclusive stdin ownership for terminal queries and subprocesses
- [register-event-handler](register-event-handler): pattern-based raw stdin → Textual message routing
- [DnD](dnd): kitty drag-and-drop protocol via `DNDApp`
