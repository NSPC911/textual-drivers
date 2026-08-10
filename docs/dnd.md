# DnD: kitty drag-and-drop

`textual_drivers.dnd` provides `DNDApp`, a `DrivenApp` subclass that implements the full [kitty drag-and-drop protocol](https://sw.kovidgoyal.net/kitty/desktop-integration/#drag-and-drop) for both directions:

- **Drag-in**: files dragged FROM the desktop INTO the terminal
- **Drag-out**: files dragged FROM the terminal TO the desktop

## Import

```python
from textual_drivers.dnd import (
    DNDApp,
    DragOutFinished,
    Drop,
    DropData,
    DropDataError,
    ImageLabel,
    TextLabel,
)
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
    data: list[str] | bytes
    # list[str] if it is a text/uri-list, bytes otherwise
    mime: str
    # mime type of this data chunk
```

```py
class DropDataError:
    drop_event: Drop
    mime: str
    error: str
    # POSIX error name, such as EIO or ETIMEDOUT
    description: str
```

```py
class DragOutFinished:
    cancelled: bool
    # True if the drag was cancelled, False if it completed successfully
```

## Reactive attributes

| Attribute | Type                                                   | Description                  |
| --------- | ------------------------------------------------------ | ---------------------------- |
| `state`   | `Literal["idle", "drag-in", "drag-in-rej", "drag-out"]` | Current drag-and-drop state. |

`state` is a Textual `var`, so subclasses can watch it:

```python
def watch_state(self, state: str) -> None:
    self.query_one("#status", Label).update(state)
```

The state can also be styled with TCSS after registering your widget:

```python
def on_mount(self) -> None:
    # not recommended btw, because it causes app-wide restyles
    # causing flicker and performance issues, but it works for demos
    self.app.add_dnd_class_target(self.app)
```

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
            label=TextLabel(
                text="<text to show in preview>",
                size=float,                 # scale relative to the terminal font
                background_opacity=0,       # 0 is transparent, 1024 is opaque
            ),
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

### Drag labels

`DNDDragOutOperation.label` accepts either a `TextLabel` or an `ImageLabel`. Kitty renders a `TextLabel` using the terminal font. Keep its text short because terminals may render newlines as a single line.

`ImageLabel` accepts raw PNG, RGB, or RGBA bytes. The driver base64 encodes and chunks the data for the protocol; do not base64 encode it yourself. Width and height are pixel dimensions. For raw RGB and RGBA data, pixels must use the sRGB color space.

```python
png = Path("drag-icon.png").read_bytes()
width = int.from_bytes(png[16:20], "big")
height = int.from_bytes(png[20:24], "big")
label = ImageLabel(
    data=png,
    width=width,
    height=height,
    format="png",  # also "rgb" or "rgba"
)

return DNDDragOutOperation(uris=uris, op="either", label=label)
```

#### Image label footguns

- Kitty does not accept JPEG, WebP, GIF, SVG, or other encoded image formats directly. Convert them to PNG, or decode them to raw RGB/RGBA data, before creating an `ImageLabel`.
- Pass raw image bytes to `ImageLabel.data`, not an already base64-encoded string. `textual-drivers` performs the base64 encoding required by the protocol.
- `width` and `height` must exactly match the supplied image data. Changing only these values does not resize an image and may cause Kitty to reject it with `EINVAL`.
- Kitty uses the supplied pixel dimensions for the drag preview. Sending a full-size photograph can therefore create an enormous preview and waste memory. Resize it to a thumbnail first; a height around 48–64 pixels works well for an icon-and-text card, while `256x256` is a reasonable upper bound for a generic thumbnail.
- A `TextLabel` and `ImageLabel` are alternative drag images, not layers that Kitty composites. To show an icon and text together, render both into one PNG and send that as an `ImageLabel`.
- Terminals may reject images that exceed their resource limits with `EFBIG`. Avoid transmitting full-resolution images when only a small drag preview is needed.

Pillow can decode a non-PNG image, apply its EXIF orientation, resize it while preserving its aspect ratio, and encode it as PNG. Pillow is an application dependency and is not installed by `textual-drivers`:

```python
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps


def image_label_from_file(path: Path) -> ImageLabel:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
        image.thumbnail((256, 256), Image.Resampling.LANCZOS)

        output = BytesIO()
        image.save(output, format="PNG")
        return ImageLabel(
            data=output.getvalue(),
            width=image.width,
            height=image.height,
            format="png",
        )


label = image_label_from_file(Path("drag-preview.jpg"))
return DNDDragOutOperation(uris=uris, op="either", label=label)
```

Pillow does not decode SVG files by default. Rasterize SVG input with a library such as CairoSVG first, then send the resulting PNG bytes.

The older `popup_text` and `popup_size` arguments remain supported for compatibility and produce a `TextLabel`. New code should use `label`.

## Requesting data

When you receive the Drop event (from `on_drop`, or `@on(Drop)`), the actual data is not yet available. You must request it. `DropData` is posted once all chunks have arrived and been assembled. For `text/uri-list`, comment lines and blank lines are stripped and each URI is an element of `data`.

If Kitty reports an error, or no data arrives for 30 seconds, `DropDataError` is posted and the entire drop is cancelled. A successful empty MIME is still reported as `DropData` with `data=b""`.

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

The drag-out demo uses a text label normally. If exactly one PNG is selected, it uses that PNG as the drag image so image labels can be tested directly in Kitty.
