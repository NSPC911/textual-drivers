"""
Interactive test app for textual-drivers.

Left panel — lock_stdin
    Click the button to hold the stdin lock for 3 s.
    Type keys during the countdown: on_key fires zero times while locked.
    On unlock, all buffered keystrokes arrive in one burst — proving the
    input thread was truly paused.

Right panel — register_event_handler
    Two handlers are registered on start-up:
      "?"     matches exactly one character  → fires on every plain keypress
      "\\x1b*"  matches any ESC-led sequence  → fires on arrow / function keys
    Both counters and a live log show matches in real time.
"""

from __future__ import annotations

import asyncio
import time

from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Button, Footer, Header, Label, Log

from textual_drivers import DrivenApp

# -- Custom messages --


class SingleCharInput(Message):
    """Fired when a single-character raw stdin chunk is received."""

    def __init__(self, data: str) -> None:
        super().__init__()
        self.data = data


class EscapeSeqInput(Message):
    """Fired when a raw stdin chunk begins with ESC (arrow keys, etc.)."""

    def __init__(self, data: str) -> None:
        super().__init__()
        self.data = data


# -- App --


class DriverTestApp(DrivenApp):
    """Test app for CustomLinuxDriver / CustomWindowsDriver features."""

    TITLE = "textual-drivers test"
    BINDINGS = [Binding("ctrl+c", "quit", "Quit")]

    CSS = """
    Screen { layout: horizontal; }

    .panel {
        width: 1fr;
        height: 100%;
        border: round $primary;
        margin: 1;
        padding: 1;
    }
    .panel-title { text-style: bold; color: $accent; margin-bottom: 1; }

    #lock-status { margin-bottom: 1; }
    .locked   { color: $error; }
    .unlocked { color: $success; }

    #lock-btn { margin-bottom: 1; }

    .hint {
        color: $text-muted;
        margin-bottom: 1;
    }

    Log { height: 1fr; border: tall $panel; }
    """

    def compose(self) -> ComposeResult:
        yield Header()

        with Vertical(classes="panel"):
            yield Label("lock_stdin", classes="panel-title")
            yield Label("Status: unlocked", id="lock-status", classes="unlocked")
            yield Button("Lock stdin for 3 s", id="lock-btn")
            yield Label(
                "Tip: type keys while locked — they arrive as a burst on unlock.",
                classes="hint",
            )
            yield Log(id="key-log", highlight=True)

        with Vertical(classes="panel"):
            yield Label("register_event_handler", classes="panel-title")
            yield Label('Pattern "?"    single-char  matches: 0', id="single-label")
            yield Label('Pattern "\\x1b*"  ESC-seq      matches: 0', id="esc-label")
            yield Label("", classes="hint")
            yield Log(id="handler-log", highlight=True)

        yield Footer()

    def on_mount(self) -> None:
        self._single_count = 0
        self._esc_count = 0

        driver = self._driver
        # "?" matches exactly one character (every plain keypress)
        driver.register_event_handler("?", SingleCharInput)
        # "\x1b*" matches any chunk starting with ESC (arrow keys, F-keys, etc.)
        driver.register_event_handler("\x1b*", EscapeSeqInput)

        log = self.query_one("#handler-log", Log)
        log.write_line('registered "?"    → SingleCharInput')
        log.write_line('registered "\\x1b*" → EscapeSeqInput')
        log.write_line("─" * 40)

    # ── lock_stdin panel ─────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "lock-btn":
            event.button.disabled = True
            self._run_lock()

    @work
    async def _run_lock(self) -> None:
        """Worker thread: holds lock_stdin for 3 s, updating the UI each second."""
        status = self.query_one("#lock-status", Label)
        btn = self.query_one("#lock-btn", Button)
        key_log = self.query_one("#key-log", Log)

        key_log.write_line(f"[{_ts()}] --- lock acquired ---")

        with self._driver.lock_stdin():
            for remaining in (3, 2, 1):
                status.update(f"Status: LOCKED — {remaining}s")
                status.set_class(True, "locked")
                status.set_class(False, "unlocked")
                self.notify("hi", timeout=1)
                await asyncio.sleep(1)

        key_log.write_line(
            f"[{_ts()}] --- lock released — buffered keys appear below ---"
        )
        status.update("Status: unlocked")
        status.set_class(True, "unlocked")
        status.set_class(False, "locked")
        btn.disabled = False

    def on_key(self, event: events.Key) -> None:
        self.query_one("#key-log", Log).write_line(f"[{_ts()}] key={event.key!r}")

    # ── register_event_handler panel ─────────────────────────────────────────

    def on_single_char_input(self, event: SingleCharInput) -> None:
        self._single_count += 1
        self.query_one("#single-label", Label).update(
            f'Pattern "?"    single-char  matches: {self._single_count}'
        )
        self.query_one("#handler-log", Log).write_line(
            f"[{_ts()}] single-char  data={event.data!r}"
        )

    def on_escape_seq_input(self, event: EscapeSeqInput) -> None:
        self._esc_count += 1
        self.query_one("#esc-label", Label).update(
            f'Pattern "\\x1b*"  ESC-seq      matches: {self._esc_count}'
        )
        self.query_one("#handler-log", Log).write_line(
            f"[{_ts()}] escape-seq   data={event.data!r}"
        )


def _ts() -> str:
    return time.strftime("%H:%M:%S")


if __name__ == "__main__":
    DriverTestApp().run()
