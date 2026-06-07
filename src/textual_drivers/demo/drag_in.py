"""kitty drag-in demo — drag files FROM the desktop/OS INTO the terminal."""

from __future__ import annotations

import re
from typing import Literal, cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Footer, Header, Label, Log, Static

from textual_drivers import BoundedPattern, DrivenApp
from textual_drivers._utils import b64decode, safe

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
            r"(?::X=(?P<X>-?\d+):Y=(?P<Y>-?\d+):o=(?P<o>\d+)[^;]*;(?P<mimes>[^\x1b]*))?",
            data,
        )
        if not m:
            raise ValueError(f"Invalid DragOver data: {data!r}")
        self.x = int(m.group("x"))
        self.y = int(m.group("y"))
        self.X = int(m.group("X")) if m.group("X") is not None else None
        self.Y = int(m.group("Y")) if m.group("Y") is not None else None
        self.o = (
            cast(Literal[1, 2, 3], int(m.group("o")))
            if m.group("o") is not None
            else None
        )
        self.mimes: list[str] | None = (
            m.group("mimes").split() if m.group("mimes") else None
        )


class Drop(Message):
    """Terminal sends this when the user releases the drag over the app.

    Format: ESC ] 72 ; t=M:x=<cx>:y=<cy>:X=<px>:Y=<py>:o=<op>;<mimes> ESC \\

    Unlike DragOver, all fields are always present (you can't drop outside the window).
    """

    x: int
    y: int
    X: int
    Y: int
    o: Literal[1, 2, 3]
    mimes: list[str]

    def __init__(self, data: str) -> None:
        super().__init__()
        m = re.search(
            r"t=M:x=(?P<x>\d+):y=(?P<y>\d+):X=(?P<X>\d+):Y=(?P<Y>\d+):o=(?P<o>\d+)[^;]*;(?P<mimes>[^\x1b]*)",
            data,
        )
        if not m:
            raise ValueError(f"Invalid Drop data: {data!r}")
        self.x = int(m.group("x"))
        self.y = int(m.group("y"))
        self.X = int(m.group("X"))
        self.Y = int(m.group("Y"))
        self.o = cast(Literal[1, 2, 3], int(m.group("o")))
        self.mimes = m.group("mimes").split() if m.group("mimes") else []


class DataChunk(Message):
    """Terminal sends this with dropped file data after the app requests it.

    Format: ESC ] 72 ; t=r:x=<idx>:m=<more>;<b64data> ESC \\

    m=0 = last (or only) chunk; m=1 = more chunks follow for the same MIME index.
    data is the base64-decoded bytes for this chunk.
    """

    idx: int
    more: bool
    data: str

    def __init__(self, data: str) -> None:
        super().__init__()
        m = re.search(
            r"t=r:x=(?P<idx>\d+):m=(?P<more>[01]);(?P<b64data>[^\x1b]*)",
            data,
        )
        if not m:
            raise ValueError(f"Invalid DataChunk data: {data!r}")
        self.idx = int(m.group("idx"))
        self.more = m.group("more") == "1"
        self.data = b64decode(m.group("b64data"))

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

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Drag a file from your file manager into this window", id="hint")
        yield Static("Waiting for drag…", id="drop-zone")
        yield Log(id="log", highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        driver = self._driver
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=m:", end=_ST),
            safe(DragOver),
        )
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=M:", end=_ST),
            safe(Drop),
        )
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=r:", end=_ST),
            safe(DataChunk),
        )
        self._data_buf: str = ""
        self._write(_osc72("t=a", "*/*"))
        self._log("Announced drag-in capability")

    def on_drag_over(self, msg: DragOver) -> None:
        if msg.x == -1 and msg.y == -1:
            self._update_hover_ui(msg)
            return
        mimes = msg.mimes or []
        op = 1 if (msg.o or 0) in (1, 3) else msg.o or 1
        self._write(_osc72(f"t=m:o={op}", " ".join(mimes)))
        self._update_hover_ui(msg)

    # @throttle(0.2)
    def _update_hover_ui(self, msg: DragOver) -> None:
        zone = self.query_one("#drop-zone", Static)
        if msg.x == -1 and msg.y == -1:
            zone.remove_class("hovering")
            zone.update("Drag left the window — drop here to transfer")
            self._log("Drag left window")
            return
        ops = {1: "copy", 2: "move"}
        op_str = ops.get(msg.o or 0, "unknown op")
        mime_str = ", ".join(msg.mimes or []) or "?"
        zone.add_class("hovering")
        zone.update(
            f"[bold]Hovering[/bold] at cell ({msg.x}, {msg.y})\n"
            f"Operation: {op_str}  |  MIME types: {mime_str}"
        )
        self._log(f"Hover ({msg.x},{msg.y}) op={msg.o} mimes={msg.mimes}")

    def on_drop(self, msg: Drop) -> None:
        zone = self.query_one("#drop-zone", Static)
        zone.remove_class("hovering")
        ops = {1: "copy", 2: "move", 3: "copy or move"}
        zone.update(
            f"[bold]Dropped![/bold] at cell ({msg.x}, {msg.y})\n"
            f"Operation: {ops.get(msg.o, '?')}  |  Fetching file list…"
        )
        self._log(f"Drop at ({msg.x},{msg.y}) op={msg.o} mimes={msg.mimes}")
        try:
            idx = msg.mimes.index("text/uri-list") + 1  # 1-based
        except ValueError:
            self._log("No text/uri-list in offered MIME types")
            self._write(_osc72("t=r:o=0"))
            return
        self._data_buf = ""
        self._write(_osc72(f"t=r:x={idx}"))
        self._log(f"Requested text/uri-list (MIME index {idx})")

    def on_data_chunk(self, msg: DataChunk) -> None:
        self._data_buf += msg.data
        if msg.more:
            return
        uris = [
            line
            for line in self._data_buf.splitlines()
            if line and not line.startswith("#")
        ]
        self._log(f"Received {len(uris)} file(s):")
        for uri in uris:
            self._log(f"  {uri}")
        zone = self.query_one("#drop-zone", Static)
        zone.update(
            f"[bold]Dropped {len(uris)} file{'s' if len(uris) != 1 else ''}[/bold]\n"
            + "\n".join(uri.removeprefix("file://") for uri in uris)
        )
        self._write(_osc72("t=r:o=1"))
        self._log("Signalled done (copy)")

    async def action_quit(self) -> None:
        self._write(_osc72("t=a"))
        await super().action_quit()

    def _write(self, seq: str) -> None:
        self._driver.write(seq)
        self._driver.flush()

    def _log(self, msg: str) -> None:
        self.query_one("#log", Log).write_line(msg)


if __name__ == "__main__":
    DragInApp().run()
