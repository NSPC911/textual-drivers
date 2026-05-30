from __future__ import annotations

import threading
from asyncio import AbstractEventLoop
from ctypes import byref
from ctypes.wintypes import DWORD
from typing import TYPE_CHECKING, Callable

from textual import constants
from textual._xterm_parser import XTermParser
from textual.drivers import win32
from textual.drivers.win32 import (
    INPUT_RECORD,
    KERNEL32,
    STD_INPUT_HANDLE,
    GetStdHandle,
    wait_for_handles,
)
from textual.drivers.windows_driver import WindowsDriver
from textual.events import Event, Resize
from textual.geometry import Size

from textual_drivers._mixin import CustomDriverMixin

if TYPE_CHECKING:
    from textual.app import App

_KEY_EVENT = 0x0001
_WINDOW_BUFFER_SIZE_EVENT = 0x0004


class _CustomEventMonitor(win32.EventMonitor):
    """EventMonitor that respects the stdin lock and dispatches custom handlers."""

    def __init__(
        self,
        loop: AbstractEventLoop,
        app: App,
        exit_event: threading.Event,
        process_event: Callable[[Event], None],
        stdin_lock: threading.Lock,
        dispatch_handlers: Callable[[str], None],
    ) -> None:
        super().__init__(loop, app, exit_event, process_event)
        self._stdin_lock = stdin_lock
        self._dispatch_handlers = dispatch_handlers

    def run(self) -> None:  # noqa: C901
        exit_requested = self.exit_event.is_set
        parser = XTermParser(debug=constants.DEBUG)

        try:
            read_count = DWORD(0)
            hIn = GetStdHandle(STD_INPUT_HANDLE)

            MAX_EVENTS = 1024
            arrtype = INPUT_RECORD * MAX_EVENTS
            input_records = arrtype()
            ReadConsoleInputW = KERNEL32.ReadConsoleInputW
            keys: list[str] = []

            while not exit_requested():
                for event in parser.tick():
                    self.process_event(event)

                if wait_for_handles([hIn], 100) is None:
                    continue

                with self._stdin_lock:
                    ReadConsoleInputW(
                        hIn, byref(input_records), MAX_EVENTS, byref(read_count)
                    )
                    read_input_records = input_records[: read_count.value]

                    del keys[:]
                    new_size: tuple[int, int] | None = None

                    for input_record in read_input_records:
                        event_type = input_record.EventType
                        if event_type == _KEY_EVENT:
                            key_event = input_record.Event.KeyEvent
                            key = key_event.uChar.UnicodeChar
                            if key_event.bKeyDown:
                                if (
                                    key_event.dwControlKeyState
                                    and key_event.wVirtualKeyCode == 0
                                ):
                                    continue
                                keys.append(key)
                        elif event_type == _WINDOW_BUFFER_SIZE_EVENT:
                            size = input_record.Event.WindowBufferSizeEvent.dwSize
                            new_size = (size.X, size.Y)

                    if keys:
                        # https://github.com/Textualize/textual/issues/3178
                        key_string = (
                            "".join(keys).encode("utf-16", "surrogatepass").decode("utf-16")
                        )
                        self._dispatch_handlers(key_string)
                        for event in parser.feed(key_string):
                            self.process_event(event)

                    if new_size is not None:
                        self.on_size_change(*new_size)

        except Exception as error:
            self.app.log.error("EVENT MONITOR ERROR", error)

    def on_size_change(self, width: int, height: int) -> None:
        """Handle a terminal resize."""
        from asyncio import run_coroutine_threadsafe

        size = Size(width, height)
        event = Resize(size, size)
        run_coroutine_threadsafe(self.app._post_message(event), loop=self.loop)


class CustomWindowsDriver(CustomDriverMixin, WindowsDriver):
    """WindowsDriver with lock_stdin and register_event_handler support."""

    def start_application_mode(self) -> None:
        """Start application mode using the custom event monitor."""
        import asyncio

        loop = asyncio.get_running_loop()

        self._restore_console = win32.enable_application_mode()

        from textual.drivers._writer_thread import WriterThread

        self._writer_thread = WriterThread(self._file)
        self._writer_thread.start()

        self.write("\x1b[?1049h")
        self._enable_mouse_support()
        self.write("\x1b[?25l")
        self.write("\033[?1004h")
        self.write("\x1b[>1u")
        self.flush()
        self._enable_bracketed_paste()

        self._event_thread = _CustomEventMonitor(
            loop,
            self._app,
            self.exit_event,
            self.process_message,
            self._stdin_lock,
            self._dispatch_custom_handlers,
        )
        self._event_thread.start()
