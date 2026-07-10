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

## Reactive attributes

| Attribute         | Type   | Description                                                                         |
| ----------------- | ------ | ----------------------------------------------------------------------------------- |
| `is_dragging_out` | `bool` | `True` while a drag-out is in progress (between the gesture and `DragOutFinished`). |
| `is_dragging_in`  | `bool` | `True` while an accepted drag-in is hovering over the window.                       |
| `is_drag_in_rej`  | `bool` | `True` while a drag-in is hovering but was rejected by `dnd_drag_in_operation`.     |

All three are Textual `var`s, so subclasses can watch them:

```python
def watch_is_dragging_out(self, active: bool) -> None:
    self.query_one("#status", Label).update("Dragging…" if active else "Idle")
```

They can also be styled with TCSS via their toggle classes:

```css
DNDApp.drag-in-active {
  background: green;
}
DNDApp.drag-in-rejected {
  background: red;
}
DNDApp.drag-out-active {
  background: blue;
}
```

## Override methods

```python
class DNDApp(DrivenApp):
    async def dnd_drag_out_operation(
        self, pos: Offset
    ) -> DNDDragOutOperation | None:
        """Return DNDDragOutOperation to start a drag-out, or None to cancel."""
        return DNDDragOutOperation(
            uris=["<list of file URIs>"],
            op="copy|move|either",
            popup_text="<text to show in preview>",
            popup_size=int                  # larger gives a smaller popup
        )

    async def dnd_drag_in_operation(self, event: DNDDragIn) -> DNDDragInOperation | bool:
        """Return DNDDragInOperation to customize the drag-in, or bool for simple accept/reject."""
        return DNDDragInOperation(
            accepted=bool,                  # explicitly state whether to accept or reject the drag-in
            op="copy|move|either",
            mimes=["<list of MIME types>"]  # list of MIME types to accept
        )
        # alternatively, just return True to accept the drag-in with default settings, or False to reject it
```

### Operations

`DNDDragOutOperation.op` accepts `"copy"`, `"move"` or `"either"`. Prefer `"either"` — it lets the drop target pick, so both copy-only and move-only targets can accept the drag.

`DNDDragInOperation.op` also accepts all three, but the kitty protocol requires a concrete operation in the hover reply: `"either"` resolves to whichever operation the drag source offers (preferring copy). If the source only offers `"move"` and you reply `"copy"` (or vice versa), the drop is refused — check `event.op` if you need to reject incompatible drags yourself.

## Requesting data

When you receive the Drop event (from `on_drop`, or `@on(Drop)`), the actual data is not yet available. You must request it. `DropData` is posted once all chunks have arrived and been assembled. For `text/uri-list`, comment lines and blank lines are stripped and each URI is an element of `data`. Assembly (base64 decode) runs in a background thread, so large binary MIME types like `image/png` do not block the UI.

If no data arrives within 30 seconds, `DropData` is posted with `data=b""` as a timeout sentinel — check for this before processing.

### Single MIME (auto-close)

If you only need one data, just call it directly in `on_drop` and the session will close automatically once the data arrives:

```python
async def on_drop(self, event: Drop) -> None:
    idx = event.mimes.index("text/uri-list")
    self.request_data(event, idx)
```

### Multiple MIMEs (explicit close)

If you need multiple data formats, you must include `close=False` in `request_data` to keep the session open across multiple requests, and call `close_dnd()` when you're truly done. `close_dnd` reports the concluded operation back to the drag source (defaulting to the drop's operation, so a `"move"` drop tells the source to remove the originals); pass `"cancel"` to abort:

```python
@work
async def on_drop(self, event: Drop) -> None:
    self._requested: list[str] = []
    self.request_data(event, 0, close=False)   # fetch first MIME, leave session open

@work
async def on_drop_data(self, event: DropData) -> None:
    self._requested.append(event.mime)
    remaining = [m for m in event.drop_event.mimes if m not in self._requested]
    if not remaining:
        self.close_dnd()
        return
    # optionally ask the user which to fetch next, then:
    idx = event.drop_event.mimes.index(remaining[0])
    self.request_data(event.drop_event, idx, close=False)
```

## Running the bundled demos

```
# test drag in
uv run python -m textual_drivers.demo.drag_in

# test drag out
uv run python -m textual_drivers.demo.drag_out
```
