# textual-drivers

Drop-in subclasses of Textual's built-in terminal drivers with two extra capabilities:

- **`lock_stdin`** — pause the driver's stdin thread and silence terminal events so you can run terminal queries or subprocesses without interference
- **`register_event_handler`** — bind a pattern against raw stdin; when it matches, a `Message` is posted into Textual's event system

A higher-level **`DNDApp`** base class builds on these to implement the full kitty drag-and-drop protocol (drag-in and drag-out).

## Installation

```
uv add textual-drivers
```

## Quick start

```python
from textual_drivers import DrivenApp

class MyApp(DrivenApp):
    ...

MyApp().run()
```

`DrivenApp` picks the right platform driver automatically.

## Documentation

Full docs are on the [wiki](../../wiki):

- [Drivers](../../wiki/drivers) — driver classes, `DrivenApp`, and mixin usage
- [lock_stdin](../../wiki/lock-stdin) — exclusive stdin ownership for terminal queries and subprocesses
- [register_event_handler](../../wiki/register-event-handler) — pattern-based raw stdin → Textual message routing
- [DnD](../../wiki/dnd) — kitty drag-and-drop protocol via `DNDApp`

The `docs/` folder in this repo mirrors the wiki and can be pushed to it with:

```
git -C docs push https://github.com/NSPC911/textual-drivers.wiki.git HEAD:master
```
