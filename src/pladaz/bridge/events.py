"""Thread-safe EventDispatcher for sending events from Python Core to UI (SYSTEM_DESIGN.md 3.3)."""

import json
from threading import Lock
from typing import Any, Callable, Optional, Protocol

from pladaz.bridge.dto import (
    sdcard_status_to_dto,
    structured_error_to_dto,
    task_to_dto,
)
from pladaz.domain.enums import Stage
from pladaz.domain.models import SDCardStatus, StructuredError, TrackTask

EventListener = Callable[[str, dict[str, Any]], None]


class JsWindowProtocol(Protocol):
    """Protocol for pywebview Window object supporting evaluate_js."""

    def evaluate_js(self, script: str) -> Any:
        ...


class EventDispatcher:
    """Dispatches thread-safe events to subscribed Python listeners and pywebview's window.pladazDispatchEvent."""

    EVENT_QUEUE_UPDATED = "queue:updated"
    EVENT_TASK_PROGRESS = "task:progress"
    EVENT_TASK_STATUS_CHANGED = "task:status_changed"
    EVENT_TASK_CONFLICT_PROMPT = "task:conflict_prompt"
    EVENT_SDCARD_STATUS_CHANGED = "sdcard:status_changed"
    EVENT_SYSTEM_ERROR = "system:error"

    def __init__(self, window: Optional[JsWindowProtocol] = None) -> None:
        self._window = window
        self._lock = Lock()
        self._listeners: list[EventListener] = []

    def set_window(self, window: Optional[JsWindowProtocol]) -> None:
        with self._lock:
            self._window = window

    def subscribe(self, listener: EventListener) -> None:
        """Register an in-process listener callback `(event_type, data_dict)`."""
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def unsubscribe(self, listener: EventListener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def dispatch(self, event_type: str, data: dict[str, Any]) -> None:
        """Thread-safely dispatch `event_type` with JSON-serializable `data`."""
        envelope = {
            "event_type": event_type,
            "data": data,
        }
        # Verify JSON serializability immediately so no non-serializable object ever crosses the bridge
        serialized = json.dumps(envelope, ensure_ascii=False)

        with self._lock:
            listeners_snapshot = list(self._listeners)
            window_ref = self._window

        for listener in listeners_snapshot:
            try:
                listener(event_type, data)
            except Exception:
                pass

        if window_ref is not None:
            try:
                window_ref.evaluate_js(f"window.pladazDispatchEvent({serialized})")
            except Exception:
                pass

    def emit_queue_updated(self, tasks: list[TrackTask]) -> None:
        self.dispatch(
            self.EVENT_QUEUE_UPDATED,
            {"tasks": [task_to_dto(t) for t in tasks]},
        )

    def emit_task_progress(
        self,
        task_id: str,
        stage: Optional[Stage],
        progress_percent: float,
        speed_str: str = "",
        eta_str: str = "",
    ) -> None:
        self.dispatch(
            self.EVENT_TASK_PROGRESS,
            {
                "task_id": task_id,
                "stage": stage.value if stage is not None else None,
                "progress_percent": float(progress_percent),
                "speed_str": speed_str,
                "eta_str": eta_str,
            },
        )

    def emit_task_status_changed(self, task: TrackTask) -> None:
        self.dispatch(
            self.EVENT_TASK_STATUS_CHANGED,
            {"task": task_to_dto(task)},
        )

    def emit_task_conflict_prompt(
        self,
        task_id: str,
        existing_path: str,
        metadata_summary: dict[str, Any],
    ) -> None:
        self.dispatch(
            self.EVENT_TASK_CONFLICT_PROMPT,
            {
                "task_id": task_id,
                "existing_path": existing_path,
                "metadata_summary": metadata_summary,
            },
        )

    def emit_sdcard_status_changed(
        self,
        status: SDCardStatus,
        alert: Optional[StructuredError] = None,
    ) -> None:
        self.dispatch(
            self.EVENT_SDCARD_STATUS_CHANGED,
            {
                "status": sdcard_status_to_dto(status),
                "alert": structured_error_to_dto(alert),
            },
        )

    def emit_system_error(self, error: StructuredError) -> None:
        self.dispatch(
            self.EVENT_SYSTEM_ERROR,
            {"error": structured_error_to_dto(error)},
        )

