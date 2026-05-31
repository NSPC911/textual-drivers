from __future__ import annotations

import fnmatch
import threading
import time
from contextlib import contextmanager
from typing import Callable, Generator

from textual.message import Message

# Every terminal event mode Textual enables on start-up that can be toggled:
#   mouse (1000/1002/1003/1006), focus tracking (1004),
#   kitty key protocol (>1u), bracketed paste (2004).
# Plain key events have no toggle — see LockStdinMixin.lock_stdin docstring.
_EVENTS_DISABLE = (
    "\x1b[?1003l"  # mouse: all-motion off
    "\x1b[?1002l"  # mouse: drag off
    "\x1b[?1000l"  # mouse: button off
    "\x1b[?1006l"  # mouse: SGR extension off
    "\x1b[?1004l"  # focus tracking off
    "\x1b[>0u"     # kitty key protocol: reset to legacy encoding
    "\x1b[?2004l"  # bracketed paste off
)
_EVENTS_ENABLE = (
    "\x1b[?1000h"
    "\x1b[?1002h"
    "\x1b[?1003h"
    "\x1b[?1006h"
    "\x1b[?1004h"
    "\x1b[>1u"
    "\x1b[?2004h"
)


class LockStdinMixin:
    """Mixin that adds lock_stdin to Textual drivers.

    Provides cooperative stdin thread pausing and automatic terminal event
    management.  Mix in before the driver class in the MRO and call
    self._stdin_pause_point() at the top of the input-thread loop.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._pause_cond: threading.Condition = threading.Condition()
        self._pause_lock_count: int = 0
        self._stdin_is_paused: bool = False

    @contextmanager
    def lock_stdin(self) -> Generator[None, None, None]:
        """Pause the stdin input thread and disable terminal event reporting.

        The input thread voluntarily stops at its next pause point (at most one
        read cycle, ≤ ~100 ms) and confirms via _stdin_is_paused before this
        yields.  All terminal event modes Textual enables (mouse, focus tracking,
        kitty key protocol, bracketed paste) are disabled for the duration so
        that no unsolicited escape sequences can arrive in stdin.  A 50 ms settle
        delay after disabling gives any already-in-transit events time to arrive
        before the caller drains the buffer.

        Plain key events cannot be disabled via escape sequences; drain stdin
        after entering the context to discard any buffered keypresses.

        Nesting multiple concurrent lock_stdin() calls is supported; event
        reporting is disabled once on the outermost entry and re-enabled once on
        the outermost exit.
        """
        with self._pause_cond:
            is_outermost = self._pause_lock_count == 0
            self._pause_lock_count += 1
            # Wait for the input thread to reach the pause point and acknowledge.
            # Timeout guards against callers that run before the thread starts.
            self._pause_cond.wait_for(lambda: self._stdin_is_paused, timeout=0.5)

        if is_outermost:
            self.write(_EVENTS_DISABLE)  # type: ignore[attr-defined]
            self.flush()  # type: ignore[attr-defined]
            # Give any in-transit events time to arrive so the caller can drain them.
            time.sleep(0.05)

        try:
            yield
        finally:
            with self._pause_cond:
                self._pause_lock_count -= 1
                outermost_releasing = self._pause_lock_count == 0
                if outermost_releasing:
                    self._pause_cond.notify_all()

            if outermost_releasing:
                self.write(_EVENTS_ENABLE)  # type: ignore[attr-defined]
                self.flush()  # type: ignore[attr-defined]

    def _stdin_pause_point(self) -> None:
        """Call at the start of each input-thread loop iteration.

        Blocks the input thread while any lock_stdin() context is active, then
        resumes when all callers have exited.
        """
        with self._pause_cond:
            if self._pause_lock_count > 0:
                self._stdin_is_paused = True
                self._pause_cond.notify_all()
                while self._pause_lock_count > 0:
                    self._pause_cond.wait(timeout=0.05)
                    exit_event: threading.Event | None = getattr(
                        self, "exit_event", None
                    )
                    if exit_event is not None and exit_event.is_set():
                        break
                self._stdin_is_paused = False


class EventHandlerMixin:
    """Mixin that adds register_event_handler to Textual drivers.

    Provides glob-pattern matching against raw stdin chunks and posting of
    matched events into Textual's event system.  Mix in before the driver
    class in the MRO and call self._dispatch_custom_handlers(data) for each
    decoded stdin chunk in the input-thread loop.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._event_handlers: list[tuple[str, Callable[[str], object]]] = []

    def register_event_handler(
        self, pattern: str, event_constructor: Callable[[str], object]
    ) -> None:
        """Register a handler fired when raw stdin input matches a glob pattern.

        Args:
            pattern: Glob pattern matched against decoded stdin chunks via fnmatch.
            event_constructor: Called with the matched data string; if the
                result is a Message instance it is posted to the app.
        """
        self._event_handlers.append((pattern, event_constructor))

    def _dispatch_custom_handlers(self, data: str) -> None:
        # for cases where multiple data is incoming, we split them based on
        # `\x1b` (ESC) and check each chunk against the registered patterns.
        for chunk in data.split("\x1b"):
            if not chunk:
                continue
            chunk = "\x1b" + chunk
            for pattern, constructor in self._event_handlers:
                if fnmatch.fnmatch(chunk, pattern):
                    event = constructor(chunk)
                    if isinstance(event, Message):
                        event.set_sender(self._app)  # type: ignore[attr-defined]
                        self.send_message(event)  # type: ignore[attr-defined]


class CustomDriverMixin(LockStdinMixin, EventHandlerMixin):
    """Convenience mixin combining LockStdinMixin and EventHandlerMixin.

    Equivalent to subclassing both individually.  Use the individual mixins
    if you only need one of the two features.
    """
