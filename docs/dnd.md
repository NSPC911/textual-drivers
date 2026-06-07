# DnD — kitty drag-and-drop

`textual_drivers.dnd` provides `DNDApp`, a `DrivenApp` subclass that implements the full [kitty drag-and-drop protocol](https://sw.kovidgoyal.net/kitty/desktop-integration/#drag-and-drop) for both directions:

- **Drag-in** — files dragged FROM the desktop/file manager INTO the terminal
- **Drag-out** — files dragged FROM the terminal TO the desktop/file manager

## Import

```python
from textual_drivers.dnd import DNDApp, Drop, DropData, DragOutFinished
```

## Messages

### Drag-in

| Message | When | Key attributes |
| --- | --- | --- |
| `DNDDragIn` | A drag is hovering over the window | `pos: (col, row)`, `op: "copy"\|"move"\|"either"`, `mimes: list[str]`. `pos == (-1, -1)` when the drag leaves the window. |
| `Drop` | The user drops content | `pos`, `op: "copy"\|"move"`, `mimes: list[str]` |
| `DropData` | Requested MIME data has been assembled | `drop_event: Drop`, `data: list[str] \| bytes` — `list[str]` for `text/uri-list` (one URI per entry, comments stripped), `bytes` otherwise |

### Drag-out

| Message | When | Key attributes |
| --- | --- | --- |
| `DragOutFinished` | Drag completes or is cancelled | `cancelled: bool` |

### Internal (do not handle directly)

`DNDDragIn`, `DragOut`, `DNDDropData` are used internally by `DNDApp` and should not be handled in subclasses.

## Override methods

```python
class DNDApp(DrivenApp):
    def dnd_drag_out_operation(
        self, pos: tuple[int, int]
    ) -> tuple[list[str], Literal["copy", "move"]] | None:
        """Return (uris, op) to start a drag-out, or None to cancel."""
        ...

    def dnd_drag_in_operation(self, event: DNDDragIn) -> bool:
        """Return True to accept the incoming drag, False to reject."""
        ...
```

## `request_data`

Call from `on_drop` to fetch actual MIME content:

```python
def on_drop(self, event: Drop) -> None:
    idx = event.mimes.index("text/uri-list")
    self.request_data(event, idx)   # 0-based index into event.mimes
```

`DropData` is posted once all chunks have arrived and been assembled. For `text/uri-list`, comment lines and blank lines are stripped and each URI is an element of `data`.

## Textual MRO dispatch — important

Textual calls **every** `on_<message>` handler in the class MRO automatically. **Never call `super()` inside an event handler** (`on_mount`, `on_dnddrag_in`, `on_drop`, etc.) — doing so causes the base-class handler to run twice, resulting in duplicate events and double-registered patterns.

```python
# WRONG
def on_mount(self) -> None:
    super().on_mount()   # DNDApp.on_mount runs a second time!
    self._log("ready")

# CORRECT
def on_mount(self) -> None:
    self._log("ready")   # Textual already called DNDApp.on_mount via MRO
```

## Drag-in example

```python
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Log, Static

from textual_drivers.dnd import DNDApp, DNDDragIn, Drop, DropData


class DragInApp(DNDApp):
    TITLE = "drag-in demo"
    BINDINGS = [Binding("ctrl+c", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Waiting for drag…", id="drop-zone")
        yield Log(id="log", highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#log", Log).write_line("Ready — drag a file from your file manager")

    def on_dnddrag_in(self, event: DNDDragIn) -> None:
        zone = self.query_one("#drop-zone", Static)
        x, y = event.pos
        if x == -1 and y == -1:
            zone.update("Drag left the window")
        else:
            zone.update(f"Hovering at ({x}, {y})  |  {', '.join(event.mimes)}")

    def on_drop(self, event: Drop) -> None:
        self.query_one("#drop-zone", Static).update("Dropped — fetching…")
        try:
            self.request_data(event, event.mimes.index("text/uri-list"))
        except ValueError:
            pass

    def on_drop_data(self, event: DropData) -> None:
        if isinstance(event.data, list):
            for uri in event.data:
                self.query_one("#log", Log).write_line(uri.removeprefix("file://"))


DragInApp().run()
```

## Drag-out example

```python
from pathlib import Path
from typing import Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Label, Log, SelectionList

from textual_drivers.dnd import DNDApp, DragOutFinished


class DragOutApp(DNDApp):
    TITLE = "drag-out demo"
    BINDINGS = [Binding("ctrl+c", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Status: idle", id="status")
        yield SelectionList[str](id="file-list")
        yield Log(id="log", highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        for entry in sorted(Path.cwd().iterdir(), key=lambda p: p.name):
            self.query_one("#file-list", SelectionList).add_option((entry.name, str(entry)))
        self.query_one("#log", Log).write_line("Select files and drag out of the window")

    def dnd_drag_out_operation(
        self, pos: tuple[int, int]
    ) -> tuple[list[str], Literal["copy", "move"]] | None:
        selected = list(self.query_one("#file-list", SelectionList).selected)
        if not selected:
            return None
        return [Path(p).as_uri() for p in selected], "copy"

    def on_drag_out_finished(self, event: DragOutFinished) -> None:
        self.query_one("#status", Label).update("Status: idle")
        self.query_one("#log", Log).write_line(
            "Drag cancelled" if event.cancelled else "Drag finished"
        )


DragOutApp().run()
```

## Running the bundled demos

```
python -m textual_drivers
```

Select `kitty_drag_in` or `kitty_drag_out` from the menu.

## Protocol internals

The kitty DnD protocol uses OSC 72 escape sequences (`\x1b]72;<meta>;<payload>\x1b\\`).

**Drag-in flow:** announce `t=a;*/*` → receive hover `t=m:` → respond `t=m:o=<op>;mimes` → receive drop `t=M:` → request data `t=r:x=<idx>` → receive chunks `t=r:x=<idx>:m=<more>;<b64>` → signal done `t=r:o=1`

**Drag-out flow:** announce `t=o:x=1` → receive gesture `t=o:x=<cx>:y=<cy>` → send MIME types + pre-send data → send icon → start drag → handle progress codes
