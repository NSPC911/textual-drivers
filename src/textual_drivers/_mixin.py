from __future__ import annotations

import fnmatch
import threading
from contextlib import contextmanager
from typing import Callable, Generator

from textual.message import Message


class CustomDriverMixin:
    """Mixin that adds lock_stdin and register_event_handler to Textual drivers."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._pause_cond: threading.Condition = threading.Condition()
        self._pause_lock_count: int = 0
        self._stdin_is_paused: bool = False
        self._event_handlers: list[tuple[str, Callable[[str], object]]] = []

    @contextmanager
    def lock_stdin(self) -> Generator[None, None, None]:
        """Pause the stdin input thread until this context manager exits.

        The input thread voluntarily stops at its next pause point (at most one
        read cycle, ≤ ~100 ms) and confirms via _stdin_is_paused before this
        yields.  Nesting multiple concurrent lock_stdin() calls is supported.
        """
        with self._pause_cond:
            self._pause_lock_count += 1
            # Wait for the input thread to reach the pause point and acknowledge.
            # Timeout guards against callers that run before the thread starts.
            self._pause_cond.wait_for(lambda: self._stdin_is_paused, timeout=0.5)
        try:
            yield
        finally:
            with self._pause_cond:
                self._pause_lock_count -= 1
                if self._pause_lock_count == 0:
                    self._pause_cond.notify_all()

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

    def register_event_handler(
        self, pattern: str, event_constructor: Callable[[str], object]
    ) -> None:
        """Register a handler fired when raw stdin input matches a glob pattern.

        Args:
            pattern: Glob pattern matched against decoded stdin chunks via fnmatch.
            event_constructor: Called with the matched pattern string; if the
                result is a Message instance it is posted to the app.
        """
        self._event_handlers.append((pattern, event_constructor))

    def _dispatch_custom_handlers(self, data: str) -> None:
        for pattern, constructor in self._event_handlers:
            if fnmatch.fnmatch(data, pattern):
                event = constructor(pattern)
                if isinstance(event, Message):
                    event.set_sender(self._app)  # type: ignore[attr-defined]
                    self.send_message(event)  # type: ignore[attr-defined]
