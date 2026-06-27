"""kitty drag-out demo — drag files FROM the terminal TO the desktop/OS."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.widgets import Footer, Header, Label, Log, SelectionList
from textual.widgets.selection_list import Selection

from textual_drivers.dnd import DNDApp, DNDDragOutOperation, DragOutFinished


class DragOutApp(DNDApp):
    TITLE = "kitty drag-out demo"

    CSS = """
    Screen { layout: vertical; }

    #hint   { color: $accent; text-style: bold; margin: 1 1 0 1; }
    #status { color: $text-muted; margin: 0 1 1 1; }

    SelectionList {
        height: 1fr;
        margin: 0 1;
        border: round $primary;
    }

    Log {
        height: 10;
        margin: 1;
        border: tall $panel;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(
            "Select files with Space, then drag out of the terminal window",
            id="hint",
        )
        yield Label("Status: idle", id="status")
        yield SelectionList[str](id="file-list")
        yield Log(id="log", highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        self._populate_file_list()
        self._log("Ready — select files and drag out")

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

    async def dnd_drag_out_operation(
        self, pos: tuple[int, int]
    ) -> DNDDragOutOperation | None:
        if pos not in self.query_one("#file-list", SelectionList).content_region:
            return
        selected: list[str] = list(self.query_one("#file-list", SelectionList).selected)
        if not selected:
            self._log("No files selected — cancelling drag")
            return None
        uris = [Path(p).as_uri() for p in selected]
        names = ", ".join(Path(p).name for p in selected)
        self._log(f"Dragging {len(uris)} item(s): {names}")
        self.query_one("#status", Label).update(f"Status: dragging {len(uris)} item(s)")
        n = len(uris)
        text = f"{n} file{'s' if n != 1 else ''}"
        return DNDDragOutOperation(uris, "copy", text)

    async def on_drag_out_finished(self, event: DragOutFinished) -> None:
        self.query_one("#status", Label).update("Status: idle")
        self._log("Drag cancelled" if event.cancelled else "Drag finished")

    def _log(self, msg: str) -> None:
        self.query_one("#log", Log).write_line(msg)


if __name__ == "__main__":
    DragOutApp().run()
