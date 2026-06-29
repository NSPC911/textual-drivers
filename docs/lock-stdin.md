# lock_stdin

`lock_stdin()` is a context manager on the driver that gives you **exclusive** ownership of stdin for the duration of the block.

## What it does

On **entry** it:

1. Pauses the driver's stdin reader thread (cooperative pause via `threading.Condition`, ≤ ~100 ms to acknowledge).
2. Disables all terminal event reporting that Textual enables (like mouse tracking, focus tracking, kitty key protocol, and bracketed paste) so no weird escape sequences arrive while you hold the lock.
3. Drains bytes already queued in stdin on POSIX ttys before yielding, avoiding a fixed settle delay on every lock.

On **exit**, event reporting is re-enabled and the input thread resumes. Nesting is supported, though not recommended; the disable/re-enable only happens on the outermost entry and exit.

## Notes

- `lock_stdin()` waits up to 0.5 s for the input thread to acknowledge the pause. If called before the input thread starts (or after it stops) it proceeds immediately.
- Plain key events **cannot** be disabled via escape sequences. `lock_stdin()` drains bytes that are already buffered on POSIX ttys, but terminal or network latency can still deliver bytes after the drain.
- `lock_stdin()` pauses Textual's stdin reader and silences terminal events, but does **not** restore the terminal to cooked/canonical mode. If your subprocess needs line-buffered input (e.g. `input()` or a shell), call the [`app.suspend()`](https://textual.textualize.io/api/app/#textual.app.App.suspend) context manager.

## Example — querying the terminal

```python
import os
import select
import sys
from textual.app import ComposeResult
from textual.widgets import Button
from textual_drivers import DrivenApp

class MyApp(DrivenApp):
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
