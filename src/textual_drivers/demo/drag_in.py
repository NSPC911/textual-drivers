"""kitty drag-in demo — drag files FROM the desktop/OS INTO the terminal."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal, cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Footer, Header, Label, Log, Static

from textual_drivers import BoundedPattern, DrivenApp

_OSC = "\x1b]"
_ST = "\x1b\\"


def _osc72(meta: str, payload: str = "") -> str:
    if payload:
        return f"{_OSC}72;{meta};{payload}{_ST}"
    return f"{_OSC}72;{meta}{_ST}"


# -- Messages --


class DragOver(Message):
    """Terminal sends this while a drag hovers over the app.

    Format: ESC ] 72 ; t=m:x=<cx>:y=<cy>[:X=<px>:Y=<py>:o=<op>;<mimes>] ESC \\

    When the cursor leaves the app window: x=y=-1 with no X/Y/o/mimes fields.
    """

    x: int
    y: int
    X: int | None
    Y: int | None
    o: Literal[1, 2, 3] | None
    mimes: list[str] | None

    def __init__(self, data: str) -> None:
        super().__init__()
        # data is the full sequence: "\x1b]72;t=m:x=<cx>:y=<cy>[...]\x1b\\"
        # Use re.search to locate the t=m:... portion anywhere in data.
        #
        # Fields to set:
        #   self.x, self.y  — always present cell position ints
        #   self.X, self.Y  — pixel position ints, or None when outside
        #   self.o          — operation int (1=copy 2=move 3=either), or None when outside
        #   self.mimes      — list[str] of space-split MIME types, or None when outside
        #
        # Raise ValueError if the required t=m pattern is not found.
        m = re.search(
            r"t=m:x=(?P<x>-?\d+):y=(?P<y>-?\d+)"
            r"(?::X=(?P<X>-?\d+):Y=(?P<Y>-?\d+):o=(?P<o>\d+);(?P<mimes>[^\x1b]*))?",
            data,
        )
        if not m:
            raise ValueError(f"Invalid DragOver data: {data!r}")
        self.x = int(m.group("x"))
        self.y = int(m.group("y"))
        self.X = int(m.group("X")) if m.group("X") is not None else None
        self.Y = int(m.group("Y")) if m.group("Y") is not None else None
        self.o = cast(Literal[1, 2, 3], int(m.group("o"))) if m.group("o") is not None else None
        self.mimes: list[str] | None = m.group("mimes").split() if m.group("mimes") else None


def _safe(cls: type[Message]) -> Callable[[str], Message | None]:
    """Wrap a Message constructor so parse errors produce None (silently dropped)."""
    def factory(data: str) -> Message | None:
        try:
            return cls(data)
        except ValueError:
            return None
    return factory


# -- App --


class DragInApp(DrivenApp):
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
    #drop-zone.hovering {
        border: round $success;
        color: $text;
    }

    Log {
        height: 10;
        margin: 1;
        border: tall $panel;
    }
    """

    _ACCEPTED_MIMES = ["text/uri-list", "text/plain"]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Drag a file from your file manager into this window", id="hint")
        yield Static("Waiting for drag…", id="drop-zone")
        yield Log(id="log", highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        self._register_handlers()
        self._write(_osc72("t=a", "text/uri-list text/plain"))
        self._log("Announced drag-in capability")

    def _register_handlers(self) -> None:
        driver = self._driver
        driver.register_event_handler(  # type: ignore[union-attr]
            BoundedPattern(start="\x1b]72;t=m:", end=_ST),
            _safe(DragOver),
        )

    def on_drag_over(self, msg: DragOver) -> None:
        zone = self.query_one("#drop-zone", Static)
        if msg.x == -1 and msg.y == -1:
            zone.remove_class("hovering")
            zone.update("Drag left the window — drop here to transfer")
            self._log("Drag left window")
            return

        accepted = [m for m in (msg.mimes or []) if m in self._ACCEPTED_MIMES]
        if accepted:
            # Prefer copy (1); fall back to whatever the source offers if copy isn't on the table
            op = 1 if (msg.o or 0) in (1, 3) else msg.o or 1
            self._write(_osc72(f"t=m:o={op}", " ".join(accepted)))
        else:
            self._write(_osc72("t=m:o=0"))

        ops = {1: "copy", 2: "move", 3: "copy or move"}
        op_str = ops.get(msg.o or 0, "unknown op")
        mime_str = ", ".join(msg.mimes) if msg.mimes else "?"
        accept_str = ", ".join(accepted) if accepted else "none (rejecting)"
        zone.add_class("hovering")
        zone.update(
            f"[bold]Hovering[/bold] at cell ({msg.x}, {msg.y})\n"
            f"Operation: {op_str}  |  Accepting: {accept_str}"
        )
        self._log(f"Hover ({msg.x},{msg.y}) op={msg.o} accepted={accepted}")

    async def action_quit(self) -> None:
        self._write(_osc72("t=a"))
        await super().action_quit()

    def _write(self, seq: str) -> None:
        self._driver.write(seq)  # type: ignore[union-attr]
        self._driver.flush()  # type: ignore[union-attr]

    def _log(self, msg: str) -> None:
        self.query_one("#log", Log).write_line(msg)


if __name__ == "__main__":
    DragInApp().run()
