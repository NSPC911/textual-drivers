"""kitty drag-in demo — drag files FROM the desktop/OS INTO the terminal."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import HorizontalGroup
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, Log, Static

from textual_drivers.dnd import DNDApp, DNDDragIn, Drop, DropData


class DragInApp(DNDApp):
    TITLE = "kitty drag-in demo"
    BINDINGS = [Binding("ctrl+c", "quit", "Quit")]

    CSS = """
    Screen { layout: vertical; }

    #hint { color: $accent; text-style: bold; margin: 1 1 0 1; }

    #drop-zone {
        height: 1fr;
        margin: 0 1;
        border: round $primary;
        padding: 1 2;
        color: $text-muted;
        content-align: center middle;
    }
    #drop-zone.hovering { border: round $success; color: $text; }

    Log {
        height: 10;
        margin: 1;
        border: tall $panel;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Drag from anywhere into this window", id="hint")
        yield Static("Waiting for drag…", id="drop-zone")
        yield Log(id="log", highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        self._log("Ready — drag a file from your file manager")

    async def on_dnddrag_in(self, event: DNDDragIn) -> None:
        zone = self.query_one("#drop-zone", Static)
        x, y = event.pos
        if x == -1 and y == -1:
            zone.remove_class("hovering")
            zone.update("Drag left the window — drop here to transfer")
            self._log("Drag left window")
        else:
            mime_str = ", ".join(event.mimes) or "?"
            zone.add_class("hovering")
            zone.update(
                f"[bold]Hovering[/bold] at cell ({x}, {y})\n"
                f"Operation: {event.op}  |  MIME types: {mime_str}"
            )

    @work
    async def on_drop(self, event: Drop) -> None:
        zone = self.query_one("#drop-zone", Static)
        zone.remove_class("hovering")
        zone.update(
            f"Dropped at cell ({event.pos[0]}, {event.pos[1]})\n"
            f"Operation: {event.op}  |  MIME types: {', '.join(event.mimes) or '?'}"
        )
        self._log(f"Drop at {event.pos} op={event.op}")
        from .helpers import NarrowOptionsWithInput
        reqmime = await self.push_screen_wait(NarrowOptionsWithInput(event.mimes, "", "Choose a MIME type to request:"))
        if reqmime is None:
            self._log("No MIME type chosen, ignoring drop.")
            return
        idx = event.mimes.index(reqmime)
        self.request_data(event, idx)

    def on_drop_data(self, event: DropData) -> None:
        if not isinstance(event.data, list):
            self._log(f"{event.mime}: {event.data!r}")
            return
        uris: list[str] = event.data
        n = len(uris)
        self._log(f"Received {n} file(s):")
        for uri in uris:
            self._log(f"  {uri}")

    def _log(self, msg: str) -> None:
        self.query_one("#log", Log).write_line(msg)


if __name__ == "__main__":
    DragInApp().run()
