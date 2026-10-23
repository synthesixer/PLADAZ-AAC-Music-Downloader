"""BridgeAPI methods for Phase 3 queue, source, and configuration operations (SYSTEM_DESIGN.md 2.6)."""

from pathlib import Path
from typing import Any, Callable, Optional

from pladaz import __version__
from pladaz.bridge.dto import (
    history_entry_to_dto,
    sdcard_status_to_dto,
    structured_error_to_dto,
    task_to_dto,
)
from pladaz.domain.enums import ConflictAction, ConflictScope
from pladaz.domain.errors import ErrorCode, PladazError
from pladaz.services.config_store import ConfigHistoryStore
from pladaz.services.logger import build_safe_structured_error
from pladaz.services.queue_manager import DownloadQueueManager
from pladaz.services.sd_card_manager import SDCardManager
from pladaz.services.source_adapter import DownloadSourceAdapter


class BridgeAPI:
    """Native JS Bridge API exposing JSON-serializable methods without raising unhandled exceptions across JS."""

    def __init__(
        self,
        queue_manager: DownloadQueueManager,
        source_adapter: DownloadSourceAdapter,
        sd_card_manager: SDCardManager,
        config_store: ConfigHistoryStore,
        file_dialog_fn: Optional[Callable[[], Optional[str]]] = None,
    ) -> None:
        self._queue_manager = queue_manager
        self._source_adapter = source_adapter
        self._sd_card_manager = sd_card_manager
        self._config_store = config_store
        self._file_dialog_fn = file_dialog_fn

    def _error_response(self, exc: Exception) -> dict[str, Any]:
        if isinstance(exc, PladazError):
            err_dto = structured_error_to_dto(
                build_safe_structured_error(
                    code=exc.code,
                    message_en=exc.message_en,
                    recoverable=exc.recoverable,
                    task_id=exc.structured.task_id,
                    details=exc.structured.details,
                )
            )
        else:
            err_dto = structured_error_to_dto(
                build_safe_structured_error(
                    code=ErrorCode.ERR_SOURCE_EXTRACTION_FAILED,
                    message_en=str(exc) or "Unexpected error.",
                    recoverable=False,
                )
            )
        return {"success": False, "error": err_dto}

    def get_initial_state(self) -> dict[str, Any]:
        try:
            cfg = self._config_store.load_config()
            dest = str(cfg.get("destination_path") or "").strip()
            sd_dto = None
            if dest:
                sd_status = self._sd_card_manager._probe.probe_destination(Path(dest))
                sd_dto = sdcard_status_to_dto(sd_status)
            return {
                "success": True,
                "version": __version__,
                "config": cfg,
                "disclaimer_accepted": bool(cfg.get("disclaimer_accepted", False)),
                "sd_status": sd_dto,
                "queue": [task_to_dto(t) for t in self._queue_manager.get_tasks()],
            }
        except Exception as exc:
            return self._error_response(exc)

    def accept_disclaimer(self) -> dict[str, Any]:
        try:
            cfg = self._config_store.load_config()
            cfg["disclaimer_accepted"] = True
            self._config_store.save_config(cfg)
            return {"success": True}
        except Exception as exc:
            return self._error_response(exc)

    def update_config(self, partial: dict[str, Any]) -> dict[str, Any]:
        try:
            cfg = self._config_store.load_config()
            cfg.update(partial)
            self._config_store.save_config(cfg)
            return {"success": True, "config": cfg}
        except Exception as exc:
            return self._error_response(exc)

    def select_cookies_file(self, explicit_path: Optional[str] = None) -> dict[str, Any]:
        try:
            chosen = explicit_path
            if chosen is None and self._file_dialog_fn is not None:
                chosen = self._file_dialog_fn()
            cfg = self._config_store.load_config()
            cfg["cookies_file_path"] = chosen
            self._config_store.save_config(cfg)
            return {"success": True, "selected_path": chosen}
        except Exception as exc:
            return self._error_response(exc)

    def update_ytdlp_module(self) -> dict[str, Any]:
        try:
            res = self._source_adapter.update_ytdlp()
            return {
                "success": res.success,
                "old_version": res.old_version,
                "new_version": res.new_version,
                "message": res.message,
            }
        except Exception as exc:
            return self._error_response(exc)

    def enqueue_urls(self, url_text: str) -> dict[str, Any]:
        try:
            lines = [
                line.strip()
                for line in (url_text or "").splitlines()
                if line.strip()
            ]
            if not lines:
                lines = [url_text.strip()]
            added_all = []
            for url in lines:
                added = self._queue_manager.enqueue_url(url)
                added_all.extend(added)
            return {
                "success": True,
                "tasks_added": [task_to_dto(t) for t in added_all],
                "error": None,
            }
        except Exception as exc:
            res = self._error_response(exc)
            res["tasks_added"] = []
            return res

    def start_queue(self) -> dict[str, Any]:
        try:
            self._queue_manager.start_queue(background=True)
            return {"success": True}
        except Exception as exc:
            return self._error_response(exc)

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        try:
            ok = self._queue_manager.cancel_task(task_id)
            return {"success": ok}
        except Exception as exc:
            return self._error_response(exc)

    def resume_queue(self) -> dict[str, Any]:
        try:
            self._queue_manager.resume_queue(background=True)
            return {"success": True}
        except Exception as exc:
            return self._error_response(exc)

    def resolve_conflict(
        self,
        task_id: str,
        action: str,
        scope: str = "single",
    ) -> dict[str, Any]:
        try:
            self._queue_manager.resolve_conflict(
                task_id=task_id,
                action=ConflictAction(action),
                scope=ConflictScope(scope),
            )
            return {"success": True}
        except Exception as exc:
            return self._error_response(exc)

    def retry_task(self, task_id: str) -> dict[str, Any]:
        try:
            task = self._queue_manager.retry(task_id)
            if task is None:
                return {"success": False, "task": None}
            return {"success": True, "task": task_to_dto(task)}
        except Exception as exc:
            return self._error_response(exc)

    def remove_task(self, task_id: str) -> dict[str, Any]:
        try:
            ok = self._queue_manager.remove(task_id)
            return {"success": ok}
        except Exception as exc:
            return self._error_response(exc)

    def clear_completed_tasks(self) -> dict[str, Any]:
        try:
            self._queue_manager.clear_completed_tasks()
            return {"success": True}
        except Exception as exc:
            return self._error_response(exc)

    def get_history(self) -> dict[str, Any]:
        try:
            entries = self._config_store.load_history()
            return {
                "success": True,
                "entries": [history_entry_to_dto(e) for e in entries],
            }
        except Exception as exc:
            return self._error_response(exc)

