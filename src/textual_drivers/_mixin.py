from __future__ import annotations

import fnmatch
import os
import re
import sys
import threading
from contextlib import contextmanager
from typing import Any, Callable, Generator, NamedTuple, TypeAlias

from textual.message import Message
from textual.signal import Signal

from textual_drivers._utils import MessageLike

try:
    import fcntl  # ty: ignore[unresolved-import]

    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

# Every terminal event mode Textual enables on start-up that can be toggled:
#   mouse (1000/1002/1003/1006), focus tracking (1004),
#   kitty key protocol (>1u), bracketed paste (2004).
# Plain key events have no toggle - see LockStdinMixin.lock_stdin docstring.
_EVENTS_DISABLE = (
    "\x1b[?1003l"  # mouse: all-motion off
    "\x1b[?1002l"  # mouse: drag off
    "\x1b[?1000l"  # mouse: button off
    "\x1b[?1006l"  # mouse: SGR extension off
    "\x1b[?1004l"  # focus tracking off
    "\x1b[>0u"  # kitty key protocol: reset to legacy encoding
    "\x1b[?2004l"  # bracketed paste off
)
_EVENTS_ENABLE = (
    "\x1b[?1000h\x1b[?1002h\x1b[?1003h\x1b[?1006h\x1b[?1004h\x1b[>1u\x1b[?2004h"
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

    def _drain_stdin_buffer(self) -> None:
        """Drain currently buffered stdin bytes without blocking."""
        if not _HAS_FCNTL or not sys.stdin.isatty():
            return

        fd = sys.stdin.fileno()
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        try:
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            while True:
                try:
                    if not os.read(fd, 4096):
                        break
                except (BlockingIOError, OSError):
                    break
        finally:
            fcntl.fcntl(fd, fcntl.F_SETFL, flags)

    @contextmanager
    def lock_stdin(self) -> Generator[None, None, None]:
        """Pause the stdin input thread and disable terminal event reporting.

        The input thread voluntarily stops at its next pause point (at most one
        read cycle, ≤ ~100 ms) and confirms via _stdin_is_paused before this
        yields.  All terminal event modes Textual enables (mouse, focus tracking,
        kitty key protocol, bracketed paste) are disabled for the duration. Any
        bytes already queued in stdin are drained before yielding on POSIX ttys.

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
            self._drain_stdin_buffer()

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


# ------------------------------------------------------------------------------


class BoundedPattern(NamedTuple):
    """Match raw stdin data that contains a substring starting with *start* and ending with *end*.

    Useful for terminal sequences with known delimiters, e.g.
    ``BoundedPattern(start="\\x1b]72;t=o:", end="\\x1b\\\\")``.
    All non-overlapping matches within the incoming data chunk are dispatched.
    """

    start: str
    end: str


# Pattern accepted by register_event_handler:
#   str            – glob matched against tokenised stdin chunks (fnmatch)
#   BoundedPattern – greedy scan for start/end-delimited substrings
#   re.Pattern     – finditer over the raw data string
Pattern: TypeAlias = str | BoundedPattern | re.Pattern[str]

GlobMatcher: TypeAlias = Callable[[str], re.Match[str] | None]
HandlerPattern: TypeAlias = BoundedPattern | re.Pattern[str] | GlobMatcher
EventHandler: TypeAlias = tuple[HandlerPattern, Callable[[str], object], bool]
NonBoundedPattern: TypeAlias = re.Pattern[str] | GlobMatcher
NonBoundedHandler: TypeAlias = tuple[NonBoundedPattern, Callable[[str], object], bool]


def _find_bounded(
    data: str,
    start: str,
    end: str,
    first_start: int | None = None,
) -> list[str]:
    """Return all non-overlapping substrings of *data* delimited by *start*…*end*."""  # noqa: DOC201
    results: list[str] = []
    pos = 0
    s = data.find(start, pos) if first_start is None else first_start
    while True:
        if s == -1:
            break
        e = data.find(end, s + len(start))
        if e == -1:
            break
        results.append(data[s:(pos := e + len(end))])
        s = data.find(start, pos)
    return results


class EventHandlerMixin:
    """Mixin that adds register_event_handler to Textual drivers.

    Provides glob-pattern matching against raw stdin chunks and posting of
    matched events into Textual's event system.  Mix in before the driver
    class in the MRO and call self._dispatch_custom_handlers(data) for each
    decoded stdin chunk in the input-thread loop.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._event_handlers: list[EventHandler] = []
        self._non_bounded_handlers: list[NonBoundedHandler] = []
        self._has_non_bounded_handlers: bool = False
        self._bounded_prefixes: set[str] = set()
        self.raw_data_signal: Signal[str] = Signal(self._app, "raw_data")

    def register_event_handler(
        self,
        pattern: Pattern,
        event_constructor: Callable[[str], MessageLike | Any],
        *,
        priority: bool = False,
    ) -> None:
        """Register a handler fired when raw stdin input matches *pattern*.

        Args:
            pattern: One of three forms —
                ``str``: glob matched against tokenised stdin chunks (fnmatch);
                ``BoundedPattern(start, end)``: fires for every non-overlapping
                substring in the chunk that begins with *start* and ends with *end*;
                ``re.Pattern``: fires for every match of ``pattern.finditer(data)``.
            event_constructor: Called with the matched data string; if the
                result is a Message instance it is posted to the app.
            priority: If True, matched sequences are stripped from the data fed
                to XTermParser and to non-priority handlers, preventing
                double-dispatch.
        """
        if isinstance(pattern, str):
            glob_pattern = re.compile(fnmatch.translate(pattern)).match
            handler = (glob_pattern, event_constructor, priority)
            self._has_non_bounded_handlers = True
            self._event_handlers.append(handler)
            self._non_bounded_handlers.append(handler)
        elif isinstance(pattern, BoundedPattern):
            self._bounded_prefixes.add(pattern.start[:2])
            self._event_handlers.append((pattern, event_constructor, priority))
        else:
            self._has_non_bounded_handlers = True
            self._event_handlers.append((pattern, event_constructor, priority))
            self._non_bounded_handlers.append(
                (pattern, event_constructor, priority)
            )

    def _dispatch_custom_handlers(self, data: str) -> str:
        """Dispatch registered handlers and return filtered data.

        Priority handlers claim exclusive ownership of their matched sequences;
        those sequences are stripped before being fed to XTermParser and
        non-priority handlers.

        Args:
            data: A decoded chunk of stdin data to match against registered
                patterns.  This is typically the raw input from the terminal,
                before any parsing or tokenisation.

        Returns:
            The filtered data string with all priority-matched sequences removed.
        """

        self.raw_data_signal.publish(data)

        if not self._event_handlers:
            return data

        bounded_possible = True
        if self._bounded_prefixes:
            bounded_possible = False
            for prefix in self._bounded_prefixes:
                if prefix in data:
                    bounded_possible = True
                    break
        if not bounded_possible and not self._has_non_bounded_handlers:
            return data
        to_strip: list[str] | None = None
        if bounded_possible:
            for pattern, constructor, priority in self._event_handlers:
                if isinstance(pattern, BoundedPattern):
                    first_start = data.find(pattern.start)
                    if first_start == -1:
                        continue
                    chunks = _find_bounded(data, pattern.start, pattern.end, first_start)
                    for chunk in chunks:
                        if priority:
                            if to_strip is None:
                                to_strip = []
                            to_strip.append(chunk)
                        event = constructor(chunk)
                        if isinstance(event, Message):
                            event.set_sender(self._app)  # type: ignore[attr-defined]
                            self.send_message(event)  # type: ignore[attr-defined]
                elif isinstance(pattern, re.Pattern):
                    for match in pattern.finditer(data):
                        chunk = match.group()
                        if priority:
                            if to_strip is None:
                                to_strip = []
                            to_strip.append(chunk)
                        event = constructor(chunk)
                        if isinstance(event, Message):
                            event.set_sender(self._app)  # type: ignore[attr-defined]
                            self.send_message(event)  # type: ignore[attr-defined]
                else:
                    if "\x1b[" not in data:
                        chunk = "\x1b[" + data
                        if data and pattern(chunk):
                            if priority:
                                if to_strip is None:
                                    to_strip = []
                                to_strip.append(chunk)
                            event = constructor(chunk)
                            if isinstance(event, Message):
                                event.set_sender(self._app)  # type: ignore[attr-defined]
                                self.send_message(event)  # type: ignore[attr-defined]
                    else:
                        for part in data.split("\x1b["):
                            if part:
                                chunk = "\x1b[" + part
                                if pattern(chunk):
                                    if priority:
                                        if to_strip is None:
                                            to_strip = []
                                        to_strip.append(chunk)
                                    event = constructor(chunk)
                                    if isinstance(event, Message):
                                        event.set_sender(self._app)  # type: ignore[attr-defined]
                                        self.send_message(event)  # type: ignore[attr-defined]
        else:
            for pattern, constructor, priority in self._non_bounded_handlers:
                if isinstance(pattern, re.Pattern):
                    for match in pattern.finditer(data):
                        chunk = match.group()
                        if priority:
                            if to_strip is None:
                                to_strip = []
                            to_strip.append(chunk)
                        event = constructor(chunk)
                        if isinstance(event, Message):
                            event.set_sender(self._app)  # type: ignore[attr-defined]
                            self.send_message(event)  # type: ignore[attr-defined]
                    continue
                else:
                    if "\x1b[" not in data:
                        chunk = "\x1b[" + data
                        if data and pattern(chunk):
                            if priority:
                                if to_strip is None:
                                    to_strip = []
                                to_strip.append(chunk)
                            event = constructor(chunk)
                            if isinstance(event, Message):
                                event.set_sender(self._app)  # type: ignore[attr-defined]
                                self.send_message(event)  # type: ignore[attr-defined]
                    else:
                        for part in data.split("\x1b["):
                            if part:
                                chunk = "\x1b[" + part
                                if pattern(chunk):
                                    if priority:
                                        if to_strip is None:
                                            to_strip = []
                                        to_strip.append(chunk)
                                    event = constructor(chunk)
                                    if isinstance(event, Message):
                                        event.set_sender(self._app)  # type: ignore[attr-defined]
                                        self.send_message(event)  # type: ignore[attr-defined]

        if to_strip is None:
            return data

        filtered = data
        for chunk in to_strip:
            filtered = filtered.replace(chunk, "", 1)
        return filtered


__all__ = ["LockStdinMixin", "EventHandlerMixin", "BoundedPattern"]
