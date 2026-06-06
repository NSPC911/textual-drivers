"""kitty drag-out demo — drag files FROM the terminal TO the desktop/OS."""

from __future__ import annotations

import base64
import re
from collections.abc import Callable
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Footer, Header, Label, Log, SelectionList
from textual.widgets.selection_list import Selection

from textual_drivers import BoundedPattern, DrivenApp

_OSC = "\x1b]"
_ST = "\x1b\\"


def _osc72(meta: str, payload: str = "") -> str:
    if payload:
        return f"{_OSC}72;{meta};{payload}{_ST}"
    return f"{_OSC}72;{meta}{_ST}"


def _b64(data: str) -> str:
    return base64.b64encode(data.encode()).decode()


# -- Messages --

class DragGestureMsg(Message):
    """Terminal reports the user started a drag gesture.

    Format: ESC ] 72 ; t=o:x=<cx>:y=<cy>[:X=<px>:Y=<py>] ESC \\
    """

    def __init__(self, data: str) -> None:
        super().__init__()
        m = re.search(
            r"t=o:x=(?P<x>-?\d+):y=(?P<y>-?\d+)"
            r"(?::X=(?P<X>-?\d+):Y=(?P<Y>-?\d+))?",
            data,
        )
        if not m:
            raise ValueError(f"Invalid DragGesture data: {data!r}")
        self.x = int(m.group("x"))
        self.y = int(m.group("y"))
        self.X = int(m.group("X")) if m.group("X") is not None else None
        self.Y = int(m.group("Y")) if m.group("Y") is not None else None


class DragProgressMsg(Message):
    """Terminal reports drag progress or completion.

    Format: ESC ] 72 ; t=e:x=<code>[:y=<idx>][:o=<op>] ESC \\

    code: 1=accepted, 2=op-changed, 3=dropped, 4=finished, 5=data-requested
    """

    def __init__(self, data: str) -> None:
        super().__init__()
        m = re.search(
            r"t=e:x=(?P<code>\d+)(?::y=(?P<y>-?\d+))?(?::o=(?P<o>\d+))?",
            data,
        )
        if not m:
            raise ValueError(f"Invalid DragProgress data: {data!r}")
        self.code = int(m.group("code"))
        self.y = int(m.group("y")) if m.group("y") is not None else None
        self.o = int(m.group("o")) if m.group("o") is not None else None


def _safe(cls: type[Message]) -> Callable[[str], Message | None]:
    """Wrap a Message constructor so parse errors produce None (silently dropped)."""
    def factory(data: str) -> Message | None:
        try:
            return cls(data)
        except ValueError:
            return None
    return factory


# -- App --

class DragOutApp(DrivenApp):
    TITLE = "kitty drag-out demo"
    BINDINGS = [Binding("ctrl+c", "quit", "Quit")]

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

    _MIME_TYPES = ["text/uri-list", "text/plain"]

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
        self._drag_active = False
        self._populate_file_list()
        self._register_dnd_handlers()
        self._write(_osc72("t=o:x=1"))
        self._log("Announced drag capability")

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

    def _register_dnd_handlers(self) -> None:
        driver = self._driver
        driver.register_event_handler(BoundedPattern(start="\x1b]72;t=o:", end=_ST), _safe(DragGestureMsg))  # type: ignore[union-attr]
        driver.register_event_handler(BoundedPattern(start="\x1b]72;t=e:", end=_ST), _safe(DragProgressMsg))  # type: ignore[union-attr]

    # -- Drag gesture --------------------------------------------------------

    def on_drag_gesture_msg(self, msg: DragGestureMsg) -> None:
        self._log(f"Drag gesture at cell ({msg.x},{msg.y})")

        selected: list[str] = list(self.query_one("#file-list", SelectionList).selected)
        if not selected:
            self._log("No files selected — cancelling drag")
            self._write(_osc72("t=E:y=-1"))
            return

        names = ", ".join(Path(p).name for p in selected)
        self._log(f"Dragging {len(selected)} item(s): {names}")
        self._drag_active = True
        self.query_one("#status", Label).update(f"Status: dragging {len(selected)} item(s)")

        # Advertise MIME types and operation (copy only)
        self._write(_osc72("t=o:o=1", " ".join(self._MIME_TYPES)))

        # Pre-send data for each MIME type
        uri_list = "\r\n".join(Path(p).as_uri() for p in selected) + "\r\n"
        self._write(_osc72("t=p:x=0", _b64(uri_list)))
        self._log("Pre-sent text/uri-list")

        plain = "\n".join(selected) + "\n"
        self._write(_osc72("t=p:x=1", _b64(plain)))
        self._log("Pre-sent text/plain")

        # Send drag icon: x=-1 is the icon slot, y=0 = UTF-8 text format,
        # X/Y = thumbnail dimensions in cells, o=0 = full opacity.
        n = len(selected)
        icon = f"(rovr) {n} file{'s' if n != 1 else ''} selected"
        self._write(_osc72(f"t=p:x=-1:y=0:X={len(icon)}:Y=10:o=0", _b64(icon)))
        self._log(f"Sent drag icon: {icon!r}")

        # Start the drag
        self._write(_osc72("t=P:x=-1"))
        self._log("Drag started")

    # -- Drag progress -------------------------------------------------------

    def on_drag_progress_msg(self, msg: DragProgressMsg) -> None:
        if msg.code == 1:
            self._log(f"Drop target accepted (preferred MIME idx={msg.y})")
        elif msg.code == 2:
            ops = {1: "copy", 2: "move", 3: "either"}
            self._log(f"Operation changed → {ops.get(msg.o or 0, '?')}")
        elif msg.code == 3:
            self._log("Drop occurred on target")
        elif msg.code == 4:
            self._log("Drag cancelled" if msg.y == 1 else "Drag finished")
            self._drag_active = False
            self.query_one("#status", Label).update("Status: idle")
        elif msg.code == 5:
            self._log(f"Terminal requests data for MIME index {msg.y}")
            self._send_data_for(msg.y)

    def _send_data_for(self, idx: int | None) -> None:
        if idx is None:
            return
        selected: list[str] = list(self.query_one("#file-list", SelectionList).selected)
        if idx == 0:
            raw = "\r\n".join(Path(p).as_uri() for p in selected) + "\r\n"
        elif idx == 1:
            raw = "\n".join(selected) + "\n"
        else:
            self._log(f"Unknown MIME index {idx}")
            self._write(_osc72(f"t=E:y={idx}", "EINVAL:unknown MIME index"))
            return
        self._write(_osc72(f"t=e:y={idx}:m=0", _b64(raw)))
        self._log(f"Sent on-demand data for MIME index {idx}")

    # -- Quit ----------------------------------------------------------------

    async def action_quit(self) -> None:
        if self._drag_active:
            self._write(_osc72("t=E:y=-1"))
        self._write(_osc72("t=o:x=2"))
        await super().action_quit()

    # -- Helpers -------------------------------------------------------------

    def _write(self, seq: str) -> None:
        self._driver.write(seq)  # type: ignore[union-attr]
        self._driver.flush()  # type: ignore[union-attr]

    def _log(self, msg: str) -> None:
        self.query_one("#log", Log).write_line(msg)


if __name__ == "__main__":
    DragOutApp().run()
