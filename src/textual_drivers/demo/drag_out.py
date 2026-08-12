"""kitty drag-out demo - drag files FROM the terminal TO the desktop/OS."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import HorizontalGroup
from textual.geometry import Offset
from textual.widgets import Footer, Label, Log, SelectionList
from textual.widgets.selection_list import Selection

from textual_drivers.dnd import (
    DNDApp,
    DNDDragOutOperation,
    DragOutFinished,
    Drop,
    DropData,
    ImageLabel,
    TextLabel,
)


class DragOutApp(DNDApp):
    TITLE = "kitty drag-out demo"

    CSS = """
    Screen { layout: vertical; }

    #hint   {
        color: $accent;
        text-style: bold;
    }

    HorizontalGroup {
        border: solid $panel;
        margin: 0 1;
        padding: 1 1 1 4;
    }

    SelectionList {
        height: 1fr;
        margin: 0 1;
        border: round $primary;
        background: transparent;
    }

    Log {
        background: transparent;
        height: 10;
        margin: 0 1;
        padding: 0 1;
        border: solid $panel;
        scrollbar-background: transparent;
        scrollbar-corner-color: transparent;
    }
    """

    def compose(self) -> ComposeResult:
        with HorizontalGroup():
            yield Label(
                "Select files with Space, then drag out of the terminal window",
                id="hint",
            )
        yield SelectionList[str](id="file-list")
        yield Log(id="log", highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        self._populate_file_list()
        self._log("Ready - select files and drag out")
        self.add_dnd_class_target(self.app)

    def _populate_file_list(self) -> None:
        file_list = self.query_one("#file-list", SelectionList)
        try:
            entries = sorted(
                Path.cwd().iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except PermissionError:
            self._log("Permission denied reading current directory")
            return
        for entry in entries:
            label = f"[blue]{entry.name}/[/blue]" if entry.is_dir() else entry.name
            file_list.add_option(Selection(label, str(entry), initial_state=False))

    async def dnd_drag_out_operation(self, pos: Offset) -> DNDDragOutOperation | None:
        if pos not in self.query_one("#file-list", SelectionList).content_region:
            return
        selected: list[str] = list(self.query_one("#file-list", SelectionList).selected)
        if not selected:
            self._log("No files selected - cancelling drag")
            return None
        uris = [Path(p).as_uri() for p in selected]
        names = ", ".join(Path(p).name for p in selected)
        self._log(f"Dragging {len(uris)} item(s): {names}")
        n = len(uris)
        text = f" {n} file{'s' if n != 1 else ''}"
        label: TextLabel | ImageLabel = TextLabel(text, size=4)
        if len(selected) == 1:
            path = Path(selected[0])
            if path.is_file() and path.suffix.lower() == ".png":
                try:
                    data = path.read_bytes()
                except OSError as error:
                    self._log(f"Could not read PNG drag image: {error}")
                else:
                    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
                        width = int.from_bytes(data[16:20], "big")
                        height = int.from_bytes(data[20:24], "big")
                        label = ImageLabel(data, width, height)
                        self._log(f"Using {width}x{height} PNG drag image")
        return DNDDragOutOperation(
            uris,
            "copy",
            label=label,
            extra_mimes={
                "did-you-know-you-can-do/stuff-like-this?": b"not an empty string btw",
                "this-means-you-can-read/mime-types-before-dropping": b"and-then-do-something-with-them",
            },
        )

    async def on_drag_out_finished(self, event: DragOutFinished) -> None:
        self._log("Drag cancelled" if event.cancelled else "Drag finished")

    def _log(self, msg: str) -> None:
        self.query_one("#log", Log).write_line(msg)

    async def on_drop(self, event: Drop) -> None:
        self._log(f"Dropped {event!r}")
        self._log("Don't drop here!")

    def on_drop_data(self, event: DropData) -> None:
        self._log(f"Drop data: {event!r}")


if __name__ == "__main__":
    DragOutApp().run()
