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
        self._stdin_lock: threading.Lock = threading.Lock()
        self._event_handlers: list[tuple[str, Callable[[str], object]]] = []

    @contextmanager
    def lock_stdin(self) -> Generator[None, None, None]:
        """Prevent the stdin input thread from reading while this is held."""
        with self._stdin_lock:
            yield

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
                    self.send_message(event)  # type: ignore[attr-defined]
