"""
Terminal capability checker.

Uses lock_stdin + direct stdin reads on a worker thread instead of
register_event_handler.  For a one-shot query-response this is simpler:

  1. lock_stdin() pauses the input thread, disables all terminal event
     reporting (mouse, focus, kitty key protocol, bracketed paste), and
     waits 50 ms for any in-transit events to settle.
  2. Drain any bytes still buffered in stdin (clears pre-buffered keypresses;
     plain key events are the one thing that cannot be disabled).
  3. Send the terminal query.
  4. Read the response directly from the stdin fd (with a timeout).
  5. lock_stdin() re-enables event reporting and resumes the input thread.
  6. Parse and display the result via call_from_thread.
"""

from __future__ import annotations

import os
import re
import select
import sys
import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Button, Footer, Header, Label, Log

from textual_drivers import DrivenApp


def _drain(fd: int) -> None:
    """Discard all bytes currently buffered on fd without blocking."""
    if sys.platform == "win32":
        import msvcrt

        while msvcrt.kbhit():
            msvcrt.getwch()
        return

    while select.select([fd], [], [], 0)[0]:
        os.read(fd, 4096)


def _read_until(fd: int, terminator: bytes, timeout: float) -> bytes:
    """Read from fd until terminator appears in the accumulated buffer or timeout expires.

    Returns:
        Accumulated bytes read, which may contain data past the terminator.
    """
    buf = b""
    deadline = time.monotonic() + timeout
    if sys.platform == "win32":
        import msvcrt

        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                buf += ch.encode("utf-8", errors="replace")
                if terminator in buf:
                    break
            else:
                time.sleep(0.01)
        return buf

    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        r, _, _ = select.select([fd], [], [], min(0.1, remaining))
        if r:
            chunk = os.read(fd, 4096)
            buf += chunk
            if terminator in buf:
                break
    return buf


class CapabilityCheckApp(DrivenApp):
    """Check terminal support for Sixel graphics and the Kitty image protocol."""

    TITLE = "Terminal Capability Checker"
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

    Button { margin-bottom: 1; }

    .status { margin-bottom: 1; text-style: bold; }
    .idle        { color: $text-muted; }
    .checking    { color: $warning; }
    .supported   { color: $success; }
    .unsupported { color: $error; }

    Log {
        height: 1fr;
        border: tab $panel;
        scrollbar-visibility: hidden;
    }
    """

    def compose(self) -> ComposeResult:
        """Build the two-panel layout.

        Yields:
            Textual widgets that form the UI.
        """
        yield Header()

        with Vertical(classes="panel"):
            yield Label("Sixel Graphics", classes="panel-title")
            yield Button("Check Sixel Support", id="sixel-btn")
            yield Label("—", id="sixel-status", classes="status idle")
            yield Log(id="sixel-log", highlight=True)

        with Vertical(classes="panel"):
            yield Label("Kitty Image Protocol", classes="panel-title")
            yield Button("Check Kitty Support", id="kitty-btn")
            yield Label("—", id="kitty-status", classes="status idle")
            yield Log(id="kitty-log", highlight=True)

        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Dispatch to the appropriate capability check worker."""
        if event.button.id == "sixel-btn":
            event.button.disabled = True
            self.run_worker(self._check_sixel, thread=True)
        elif event.button.id == "kitty-btn":
            event.button.disabled = True
            self.run_worker(self._check_kitty, thread=True)

    # -- sixel ----------------------------------------------------------------

    def _check_sixel(self) -> None:
        """Worker: send DA1 query and parse the response for sixel support (param 4)."""
        fd = sys.stdin.fileno()
        self._tlog("sixel", f"[{_ts()}] Sending DA1 query (ESC [ c) …")
        self._tset_status("sixel", "Checking…", "checking")

        with self._driver.lock_stdin():
            _drain(fd)
            self._driver.write("\x1b[c")
            self._driver.flush()
            raw = _read_until(fd, b"c", timeout=2.0)

        text = raw.decode("utf-8", errors="replace")
        self._tlog("sixel", f"[{_ts()}] Response: {text!r}")

        m = re.search(r"\x1b\[\?([0-9;]+)c", text)
        if not m:
            self._tset_status("sixel", "No response — not supported", "unsupported")
        else:
            params = [int(p) for p in m.group(1).split(";") if p]
            self._tlog("sixel", f"[{_ts()}] Params: {params}")
            if 4 in params:
                self._tset_status("sixel", "Sixel graphics: SUPPORTED", "supported")
            else:
                self._tset_status(
                    "sixel", f"Not supported (params {params})", "unsupported"
                )

        self.call_from_thread(self._enable_btn, "sixel-btn")

    # -- kitty ----------------------------------------------------------------

    def _check_kitty(self) -> None:
        """Worker: send a Kitty graphics query and check for an OK response."""
        fd = sys.stdin.fileno()
        self._tlog("kitty", f"[{_ts()}] Sending Kitty graphics query …")
        self._tset_status("kitty", "Checking…", "checking")

        with self._driver.lock_stdin():
            _drain(fd)
            # Minimal 1×1 query: action=query (a=q), image id=31
            self._driver.write("\x1b_Gi=31,s=1,v=1,a=q,t=d,f=24;AAAA\x1b\\")
            self._driver.flush()
            # Kitty response is terminated by ST (ESC \)
            raw = _read_until(fd, b"\x1b\\", timeout=2.0)

        text = raw.decode("utf-8", errors="replace")
        self._tlog("kitty", f"[{_ts()}] Response: {text!r}")

        if ";OK" in text:
            self._tset_status("kitty", "Kitty image protocol: SUPPORTED", "supported")
        elif text:
            m = re.search(r";([^;\x1b]+)", text)
            detail = m.group(1) if m else text.strip()
            self._tset_status("kitty", f"Not supported: {detail}", "unsupported")
        else:
            self._tset_status("kitty", "No response — not supported", "unsupported")

        self.call_from_thread(self._enable_btn, "kitty-btn")

    # -- thread-safe UI helpers -----------------------------------------------

    def _tlog(self, panel: str, msg: str) -> None:
        """Write a log line to the named panel's Log (safe to call from any thread)."""
        self.call_from_thread(self.query_one(f"#{panel}-log", Log).write_line, msg)

    def _tset_status(self, panel: str, text: str, css_class: str) -> None:
        """Update the named panel's status label (safe to call from any thread)."""

        def _update() -> None:
            label = self.query_one(f"#{panel}-status", Label)
            label.update(text)
            label.set_classes(f"status {css_class}")

        self.call_from_thread(_update)

    def _enable_btn(self, btn_id: str) -> None:
        """Re-enable a button by id."""
        self.query_one(f"#{btn_id}", Button).disabled = False


def _ts() -> str:
    return time.strftime("%H:%M:%S")


if __name__ == "__main__":
    CapabilityCheckApp().run()
