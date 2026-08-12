"""kitty drag-in demo - drag files FROM the desktop/OS INTO the terminal."""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.containers import HorizontalGroup
from textual.widgets import Button, Footer, Label, Log, Static

from textual_drivers.dnd import (
    DNDApp,
    DNDDragIn,
    DNDDragInOperation,
    Drop,
    DropData,
)


class DragInApp(DNDApp):
    TITLE = "kitty drag-in demo"

    CSS = """
    Screen {
        layout: vertical;
    }

    HorizontalGroup {
        border: solid $panel;
        margin: 0 1;
        padding: 0 1;
    }

    #hint {
        color: $accent;
        text-style: bold;
        margin: 1 1 1 3;
        width: 1fr;
    }

    #drop-zone {
        height: 1fr;
        margin: 0 1;
        border: solid $primary;
        padding: 1 2;
        color: $text-muted;
        content-align: center middle;
    }

    #drop-zone.hovering {
        border: dashed $success;
        color: $text;
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
            yield Label("Drag from anywhere into this window", id="hint")
            yield Button("Stop Drag", id="stop-drag", variant="error", tooltip="Use if the drop wasn't properly cancelled")
        yield Static("Waiting for drag…", id="drop-zone")
        yield Log(id="log", highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        self._requested_mimes: list[str] = []
        self.Log("Ready - drag a file from your file manager")
        self.add_dnd_class_target(self.app)

    async def on_dnddrag_in(self, event: DNDDragIn) -> None:
        zone = self.query_one("#drop-zone", Static)
        x, y = event.pos
        if x == -1 and y == -1:
            zone.remove_class("hovering")
            zone.update("Drag left the window - drop here to transfer")
            self.Log("Drag left window")
        else:
            mime_str = ", ".join(event.mimes) or "?"
            zone.add_class("hovering")
            zone.update(
                f"[bold]Hovering[/bold] at cell ({x}, {y})\n"
                f"Operation: {event.op}  |  MIME types: {mime_str}"
            )

    async def dnd_drag_in_operation(
        self, event: DNDDragIn
    ) -> DNDDragInOperation | bool:
        # originally I wanted to do below
        # event.pos in self.query_one("#drop-zone", Static).content_region
        # but sometimes it just doesn't drop on small windows
        # but I use small windows, so I just accept all drops for now
        return DNDDragInOperation(
            accepted=True,
            op="either",
            mimes=event.mimes,
        )

    @work
    async def on_drop(self, event: Drop) -> None:
        zone = self.query_one("#drop-zone", Static)
        zone.remove_class("hovering")
        zone.update(
            f"Dropped at cell ({event.pos[0]}, {event.pos[1]})\n"
            f"Operation: {event.op}  |  MIME types: {', '.join(event.mimes) or '?'}"
        )
        self.Log(f"Drop at {event.pos} op={event.op}")
        self._requested_mimes = []
        from .helpers import NarrowOptionsWithInput

        reqmime = await self.push_screen_wait(
            NarrowOptionsWithInput(event.mimes, "", "Choose a MIME type to request:")
        )
        if reqmime is None:
            self.Log("No MIME type chosen, ignoring drop.")
            self.close_dnd()
            return
        self._requested_mimes.append(reqmime)
        self.request_data(event, event.mimes.index(reqmime), close=False)

    @work
    async def on_drop_data(self, event: DropData) -> None:
        if not isinstance(event.data, list):
            self._log_(f"{event.mime}: {event.data!r}")
        else:
            uris: list[str] = event.data
            self._log_(f"Received {len(uris)} file(s) for {event.mime}:")
            for uri in uris:
                self._log_(f"  {uri}")

        from .helpers import NarrowOptionsWithInput

        all_mimes = event.drop_event.mimes
        remaining = [m for m in all_mimes if m not in self._requested_mimes]
        if not remaining:
            self.Log("All MIME types received.")
            self.close_dnd()
            return
        reqmime = await self.push_screen_wait(
            NarrowOptionsWithInput(
                remaining, "", "Request another MIME type? (cancel to stop)"
            )
        )
        if reqmime is None:
            self.Log("Done requesting MIME types.")
            self.close_dnd()
            return
        self._requested_mimes.append(reqmime)
        self.request_data(event.drop_event, all_mimes.index(reqmime), close=False)

    @on(Button.Pressed, "#stop-drag")
    def stop_drag(self) -> None:
        self.Log("Stopping drag")
        self.close_dnd()

    def Log(self, msg: str) -> None:  # noqa: N802
        self.query_one("#log", Log).write_line(msg)

    def _log_(self, msg: str) -> None:
        self.Log(msg)
        self.log(msg)


if __name__ == "__main__":
    DragInApp().run()
