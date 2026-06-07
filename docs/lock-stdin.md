# lock_stdin

`lock_stdin()` is a context manager on the driver that gives you exclusive ownership of stdin for the duration of the block.

## What it does

On **entry** it:

1. Pauses the driver's stdin reader thread (cooperative pause via `threading.Condition`, ≤ ~100 ms to acknowledge).
2. Disables all terminal event reporting that Textual enables — mouse tracking, focus tracking, kitty key protocol, and bracketed paste — so no unsolicited escape sequences arrive while you hold the lock.
3. Waits 50 ms for any already-in-transit events to land in the OS buffer before yielding, so a drain at the top of the block reliably clears them.

On **exit**, event reporting is re-enabled and the input thread resumes. Nesting is supported; the disable/re-enable only happens on the outermost entry and exit.

## Notes

- `lock_stdin()` waits up to 0.5 s for the input thread to acknowledge the pause. If called before the input thread starts (or after it stops) it proceeds immediately.
- Plain key events **cannot** be disabled via escape sequences. Drain stdin at the start of the block to discard any buffered keypresses — the terminal response arrives in < 1 ms, before the user can type another character.
- `lock_stdin()` pauses Textual's stdin reader and silences terminal events, but does **not** restore the terminal to cooked/canonical mode. If your subprocess needs line-buffered input (e.g. `input()` or a shell), call `suspend_application_mode()` instead.

## Example — querying the terminal

```python
import os
import select
import sys
from textual.app import App, ComposeResult
from textual.widgets import Button


class MyApp(App):
    def compose(self) -> ComposeResult:
        yield Button("Query terminal")

    def on_button_pressed(self) -> None:
        self.run_worker(self._query, thread=True)

    def _query(self) -> None:
        fd = sys.stdin.fileno()
        with self.app._driver.lock_stdin():
            # Drain buffered keypresses, then read the terminal's response directly.
            while select.select([fd], [], [], 0)[0]:
                os.read(fd, 4096)
            self.app._driver.write("\x1b[c")   # Primary Device Attributes query
            self.app._driver.flush()
            # Read until the response terminator 'c' arrives (< 1 ms round trip).
            buf = b""
            while b"c" not in buf:
                buf += os.read(fd, 4096)
```
