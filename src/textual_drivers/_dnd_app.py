"""Textual app integration for kitty drag and drop."""

from __future__ import annotations

import tempfile
from typing import Literal

from textual import events, on, work
from textual.dom import DOMNode
from textual.geometry import Offset
from textual.messages import ExitApp
from textual.reactive import var
from textual.timer import Timer

from textual_drivers import BoundedPattern, DrivenApp
from textual_drivers._dnd_protocol import DRAG_PROGRESS_RE as _DRAG_PROGRESS_RE
from textual_drivers._dnd_protocol import DROP_ERROR_RE as _DROP_ERROR_RE
from textual_drivers._dnd_protocol import ST as _ST
from textual_drivers._dnd_protocol import (
    DNDDragIn,
    DNDDragOut,
    DNDDropDataComplete,
    DNDDropDataFailed,
)
from textual_drivers._dnd_protocol import DropDataReceiver as _DropDataReceiver
from textual_drivers._dnd_protocol import (
    drag_label_sequences as _drag_label_sequences,
)
from textual_drivers._dnd_protocol import (
    drag_payload_sequences as _drag_payload_sequences,
)
from textual_drivers._dnd_protocol import osc72 as _osc72
from textual_drivers._dnd_types import (
    DNDDragInOperation,
    DNDDragOutOperation,
    DragOutFinished,
    Drop,
    DropData,
    DropDataError,
    TextLabel,
)
from textual_drivers._utils import safe


class DNDApp(DrivenApp):
    """DrivenApp subclass with kitty drag-in and drag-out support.

    Override dnd_drag_out_operation and dnd_drag_in_operation to customise
    behaviour. Handle Drop, DropData, and DNDDragOutFinished messages for events.
    """

    state: var[Literal["idle", "drag-in", "drag-in-rej", "drag-out"]] = var("idle")
    _dnd_class_targets: set[DOMNode] = set()

    def _on_mount(self) -> None:
        self._drag_uris: list[str] = []
        self._drag_data: list[str | bytes] = []
        self._drag_op: Literal["copy", "move", "either"] = "copy"
        self._current_drop: Drop | None = None
        self._drop_receiver = _DropDataReceiver()
        self._data_mime_idx: int = 0
        self._close_after_data: bool = False
        self._drop_timeout_timer: Timer | None = None
        self._drop_timeout: float = 30.0

        driver = self._driver
        if not hasattr(driver, "register_event_handler"):
            return
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=m:", end=_ST),
            safe(DNDDragIn),
            priority=True,
        )
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=o:", end=_ST),
            safe(DNDDragOut),
            priority=True,
        )
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=M:", end=_ST),
            Drop,
            priority=True,
        )
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=r:", end=_ST),
            self._drop_receiver,
            priority=True,
        )
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=R:", end=_ST),
            self._handle_drop_error,
            priority=True,
        )
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=e:", end=_ST),
            self._handle_drag_progress,
            priority=True,
        )
        driver.register_event_handler(
            BoundedPattern(start="\x1b]72;t=E:", end=_ST),
            lambda _: None,
            priority=True,
        )
        self._write(_osc72("t=o:x=1"), _osc72("t=a", "*/*"))

    def _watch_state(self, state: str) -> None:
        for widget in self._dnd_class_targets:
            widget.update_classes({
                "drag-in-active": state == "drag-in",
                "drag-in-rejected": state == "drag-in-rej",
                "drag-out-active": state == "drag-out",
            })

    async def _on_dnddrag_in(self, event: DNDDragIn) -> None:
        from inspect import isawaitable

        x, y = event.pos
        if x == -1 and y == -1:
            self.state = "idle"
            self._write(_osc72("t=m:o=0"))
            return
        result = self.dnd_drag_in_operation(event)
        if isawaitable(result):
            result = await result
        if isinstance(result, bool):
            result = DNDDragInOperation(accepted=result, op="either", mimes=event.mimes)
        if not result.accepted:
            self.state = "drag-in-rej"
            self._write(_osc72("t=m:o=0"))
            return
        self.state = "drag-in"
        op = result.op
        if op == "either":
            op = "move" if event.op == "move" else "copy"
        op_int = 2 if op == "move" else 1
        self._write(_osc72(f"t=m:o={op_int}", " ".join(result.mimes)))

    async def _on_dnddrag_out(self, event: DNDDragOut) -> None:
        from inspect import isawaitable

        returned = self.dnd_drag_out_operation(event.pos)
        result = await returned if isawaitable(returned) else returned
        if result is None:
            self._write(_osc72("t=E:y=-1"))
            return
        op_int = {"copy": 1, "move": 2, "either": 3}[result.op]
        uri_list = "\r\n".join(result.uris) + "\r\n"
        plain = "\n".join(u.removeprefix("file://") for u in result.uris) + "\n"
        label = result.label or TextLabel(result.popup_text or "", result.popup_size)
        try:
            label_sequences = _drag_label_sequences(label)
        except (TypeError, ValueError):
            self._write(_osc72("t=E:y=-1"))
            raise
        self._drag_uris = result.uris
        self._drag_data = [uri_list, plain, *result.extra_mimes.values()]
        self._drag_op = result.op
        self.state = "drag-out"
        self._write(
            _osc72(
                f"t=o:o={op_int}",
                " ".join(("text/uri-list", "text/plain", *result.extra_mimes)),
            ),
            *[
                sequence
                for index, data in enumerate(self._drag_data)
                for sequence in _drag_payload_sequences(f"t=p:x={index}", data)
            ],
            *label_sequences,
            _osc72("t=P:x=-1"),
        )

    def _on_dnddrop_data_complete(self, event: DNDDropDataComplete) -> None:
        if event.idx != self._data_mime_idx + 1:
            event.data.close()
            return
        if self._drop_timeout_timer is not None:
            self._drop_timeout_timer.stop()
            self._drop_timeout_timer = None
        if self._current_drop is None:
            event.data.close()
            return
        self._assemble_drop(
            self._current_drop,
            event.data,
            self._current_drop.mimes[self._data_mime_idx],
            self._close_after_data,
        )

    def _on_dnddrop_data_failed(self, event: DNDDropDataFailed) -> None:
        if event.idx != self._data_mime_idx + 1 or self._current_drop is None:
            return
        drop = self._current_drop
        mime = drop.mimes[self._data_mime_idx]
        self.close_dnd("cancel")
        self.post_message(DropDataError(drop, mime, "EINVAL", event.description))

    def _handle_drop_error(self, data: str) -> None:
        m = _DROP_ERROR_RE.search(data)
        if not m or self._current_drop is None:
            return
        meta = dict(
            part.split("=", 1) for part in m.group("meta").split(":") if "=" in part
        )
        if meta.get("x") != str(self._data_mime_idx + 1):
            return
        drop = self._current_drop
        mime = drop.mimes[self._data_mime_idx]
        self.close_dnd("cancel")
        self.post_message(
            DropDataError(drop, mime, m.group("error"), m.group("description") or "")
        )

    @work(thread=True)
    def _assemble_drop(
        self,
        drop: Drop,
        data: tempfile.SpooledTemporaryFile[bytes],
        mime: str,
        close: bool,
    ) -> None:
        with data:
            raw = data.read()
        assembled: list[str] | bytes
        if mime == "text/uri-list":
            assembled = [
                line
                for line in raw.decode().splitlines()
                if line and not line.startswith("#")
            ]
        else:
            assembled = raw
        self.post_message(DropData(drop, assembled, mime))
        if close:
            self.call_from_thread(self.close_dnd)

    def _handle_drag_progress(self, data: str) -> None:
        m = _DRAG_PROGRESS_RE.search(data)
        if not m:
            return
        code = m.group("code")
        if code == "4":
            was_active = self.state == "drag-out"
            if was_active:
                self.state = "idle"
            self._drag_uris = []
            self._drag_data = []
            self._write(_osc72("t=o:x=1"))
            if was_active:
                self.post_message(DragOutFinished(cancelled=m.group("y") == "1"))
        elif code == "5":
            y = m.group("y")
            if y is not None:
                self._send_drag_data(int(y))

    def _send_drag_data(self, idx: int) -> None:
        if 0 <= idx < len(self._drag_data):
            self._write(*_drag_payload_sequences(f"t=e:y={idx}", self._drag_data[idx]))

    async def on_drop(self, event: Drop) -> None:
        self.state = "idle"
        if event.rejected:
            event.stop().prevent_default()

    async def dnd_drag_out_operation(self, pos: Offset) -> DNDDragOutOperation | None:
        """Return DNDDragOutOperation to start a drag-out, or None to cancel."""  # noqa: DOC201
        return None

    async def dnd_drag_in_operation(
        self, event: DNDDragIn
    ) -> DNDDragInOperation | bool:
        """Return True to accept the incoming drag, False to reject."""  # noqa: DOC201
        return DNDDragInOperation(accepted=True, op="either", mimes=event.mimes)

    def request_data(self, event: Drop, index: int, close: bool = True) -> None:
        """Request MIME data for a drop. index is 0-based into event.mimes."""
        self._current_drop = event
        self._data_mime_idx = index
        self._drop_receiver.reset(index + 1)
        self._close_after_data = close
        self._arm_drop_timeout()
        self._write(_osc72(f"t=r:x={index + 1}"))

    def _arm_drop_timeout(self) -> None:
        if self._current_drop is None:
            return
        drop = self._current_drop
        index = self._data_mime_idx
        self._drop_timeout_timer = self.set_interval(
            max(0.01, min(1.0, self._drop_timeout)),
            lambda: self._drop_timed_out(drop, index),
            name="kitty dnd drop request timeout timer",
        )

    def _drop_timed_out(self, drop: Drop, index: int) -> None:
        if self._current_drop is not drop or self._data_mime_idx != index:
            return
        if self._drop_receiver.idle_for() < self._drop_timeout:
            return
        mime = drop.mimes[index]
        self.close_dnd("cancel")
        self.post_message(
            DropDataError(drop, mime, "ETIMEDOUT", "drop data request timed out")
        )

    def close_dnd(self, op: Literal["copy", "move", "cancel"] | None = None) -> None:
        """Close the current drop session and report its final operation."""
        if op is None:
            op = self._current_drop.op if self._current_drop is not None else "copy"
        op_int = {"cancel": 0, "copy": 1, "move": 2}[op]
        if self._drop_timeout_timer is not None:
            self._drop_timeout_timer.stop()
            self._drop_timeout_timer = None
        self._current_drop = None
        self._drop_receiver.cancel()
        self._write(_osc72(f"t=r:o={op_int}"))

    @on(events.Unmount)
    @on(events.Hide)
    @on(ExitApp)
    def stop_kitty(self) -> None:
        self.close_dnd("cancel")
        if self.state == "drag-out":
            self._write(_osc72("t=E:y=-1"))
        self._write(_osc72("t=o:x=2"), _osc72("t=A", ""))

    async def action_quit(self) -> None:
        self.stop_kitty()
        await super().action_quit()

    def add_dnd_class_target(self, widget: DOMNode) -> None:
        self._dnd_class_targets.add(widget)

    def _fatal_error(self) -> None:
        self.stop_kitty()
        return super()._fatal_error()

    def _write(self, *lines: str) -> None:
        for seq in lines:
            self._driver.write(seq)
        self._driver.flush()
