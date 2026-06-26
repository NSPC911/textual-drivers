# DnD: kitty drag-and-drop

`textual_drivers.dnd` provides `DNDApp`, a `DrivenApp` subclass that implements the full [kitty drag-and-drop protocol](https://sw.kovidgoyal.net/kitty/desktop-integration/#drag-and-drop) for both directions:

- **Drag-in**: files dragged FROM the desktop INTO the terminal
- **Drag-out**: files dragged FROM the terminal TO the desktop

## Import

```python
from textual_drivers.dnd import DNDApp, Drop, DropData, DragOutFinished
```

## Messages

### Drag-in

```py
class Drop:
    pos: Offset
    # position of the drop operation in cells, namedtuple with x and y attributes
    op: Literal["copy", "move"]
    # operation type
    mimes: list[str]
    # list of MIME types of drop
```

```py
class DropData:
    drop_event: Drop
    # the original Drop event that triggered this data arrival
    data: list[str] | btes
    # list[str] if it is a text/uri-list, bytes otherwise
    mime: str
    # mime type of this data chunk
```

```py
class DragOutFinished:
    cancelled: bool
    # True if the drag was cancelled, False if it completed successfully
```

### Internal (do not handle directly)

`DNDDragIn`, `DNDDragOut`, `DNDDropData` and `DNDDragOutOperation` are used internally by `DNDApp` and should not be handled in subclasses.

## Reactive attributes

| Attribute    | Type | Description                                                                                                                            |
| ------------ | ---- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `drag_state` | str  | "in", "out", "in-rej" or `None`, indicating the current drag state. "in-rej" means a drag-in was rejected by `dnd_drag_out_operation`. |

Reactive variables can be watched without needing to be polled

```python
def watch_drag_state(self, old: DragState | None, new: DragState | None) -> None:
    ...
```

It also automatically updates classes on the app
```css
.drag-in {
    /* drag-in is active */
}
.drag-out {
    /* drag-out is active */
}
.drag-in-rej {
    /* drag-in was rejected */
}
```

## Override methods

```python
class DNDApp(DrivenApp):
    async def dnd_drag_out_operation(
        self, pos: Offset
    ) -> DNDDragOutOperation | None:
        """Return DNDDragOutOperation to start a drag-out, or None to cancel."""
        ...

    async def dnd_drag_in_operation(self, event: DNDDragIn) -> bool:
        """Return True to accept the incoming drag, False to reject."""
        ...
```

## Requesting data

When you receive the Drop event (from `on_drop`, or `@on(Drop)`), the actual data is not yet available. You need to ask for the data

```py
async def on_drop(self, event: Drop) -> None:
    idx = event.mimes.index("text/uri-list")
    # must request here
    self.request_data(event, idx)
```

`DropData` is posted once all chunks have arrived and been assembled. For `text/uri-list`, comment lines and blank lines are stripped and each URI is an element of `data`.

### Single MIME (auto-close)

If you only need one data, just call it directly in `on_drop` and the session will close automatically once the data arrives:

```python
async def on_drop(self, event: Drop) -> None:
    idx = event.mimes.index("text/uri-list")
    self.request_data(event, idx)
```

### Multiple MIMEs (explicit close)

If you need multiple data formats, you must include `close=False` in `request_data` to keep the session open across multiple requests, and call `close_dnd()` when you're truly done:

```python
@work
async def on_drop(self, event: Drop) -> None:
    self._requested: list[str] = []
    self.request_data(event, 0)   # fetch first MIME, leave session open

@work
async def on_drop_data(self, event: DropData) -> None:
    self._requested.append(event.mime)
    remaining = [m for m in event.drop_event.mimes if m not in self._requested]
    if not remaining:
        self.close_dnd()
        return
    # optionally ask the user which to fetch next, then:
    self.request_data(event.drop_event, event.drop_event.mimes.index(remaining[0]), close=False)
    # call self.close_dnd() once truly done
```

## Running the bundled demos

```
# test drag in
uv run python -m textual_drivers.demo.drag_in

# test drag out
uv run python -m textual_drivers.demo.drag_out
```
