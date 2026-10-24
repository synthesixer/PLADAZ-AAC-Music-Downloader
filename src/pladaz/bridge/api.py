"""BridgeAPI methods for Phase 3 & Phase 4 queue, storage, source, and configuration operations (SYSTEM_DESIGN.md 2.6)."""

import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable, Optional

from pladaz import __version__
from pladaz.bridge.dto import (
    history_entry_to_dto,
    sdcard_status_to_dto,
    structured_error_to_dto,
    task_to_dto,
)
from pladaz.domain.enums import ConflictAction, ConflictScope
from pladaz.domain.errors import (
    ErrorCode,
    PladazError,
    SDCardDisconnectedError,
    SourceExtractionError,
)
from pladaz.services.browser_auth import (
    browser_label,
    detect_browsers,
    is_supported_browser,
)
from pladaz.services.config_store import (
    CONFIG_KEY_MUSICBRAINZ_USER_AGENT,
    CONFIG_KEY_REQUIRE_ALBUM_ART,
    ConfigHistoryStore,
)
from pladaz.services.logger import build_safe_structured_error, redact_sensitive_text
from pladaz.services.queue_manager import DownloadQueueManager
from pladaz.services.sd_card_manager import SDCardManager
from pladaz.services.source_adapter import DownloadSourceAdapter, _subprocess_creation_flags


# Keys update_config() may change, with their required JSON type (F-13, DEC-051).
# destination_path stays here because the backend still validates it with check_destination().
UPDATABLE_CONFIG_KEYS: dict[str, type] = {
    CONFIG_KEY_REQUIRE_ALBUM_ART: bool,
    CONFIG_KEY_MUSICBRAINZ_USER_AGENT: str,
    "destination_path": str,
}


def _query_ffmpeg_version(ffmpeg_path: Optional[Path] = None) -> str:
    target = str(ffmpeg_path) if (ffmpeg_path and Path(ffmpeg_path).exists()) else "ffmpeg"
    try:
        proc = subprocess.run(
            [target, "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5.0,
            shell=False,
            creationflags=_subprocess_creation_flags(),
        )
        if proc.returncode == 0 and proc.stdout:
            first_line = proc.stdout.splitlines()[0].strip()
            parts = first_line.split()
            if len(parts) >= 3 and parts[0].lower() == "ffmpeg" and parts[1].lower() == "version":
                return f"{parts[2]} (bundled)"
            return first_line[:36]
    except Exception:
        pass
    return "bundled"


class BridgeAPI:
    """Native JS Bridge API exposing JSON-serializable methods without raising unhandled exceptions across JS."""

    def __init__(
        self,
        queue_manager: DownloadQueueManager,
        source_adapter: DownloadSourceAdapter,
        sd_card_manager: SDCardManager,
        config_store: ConfigHistoryStore,
        file_dialog_fn: Optional[Callable[[], Optional[str]]] = None,
        folder_dialog_fn: Optional[Callable[[], Optional[str]]] = None,
        exe_dialog_fn: Optional[Callable[[], Optional[str]]] = None,
        quit_fn: Optional[Callable[[], None]] = None,
        open_folder_fn: Optional[Callable[[Path], None]] = None,
        log_file_path: Optional[Path] = None,
        ffmpeg_path: Optional[Path] = None,
    ) -> None:
        self._queue_manager = queue_manager
        self._source_adapter = source_adapter
        self._sd_card_manager = sd_card_manager
        self._config_store = config_store
        self._file_dialog_fn = file_dialog_fn
        self._folder_dialog_fn = folder_dialog_fn
        self._exe_dialog_fn = exe_dialog_fn
        self._quit_fn = quit_fn
        self._open_folder_fn = open_folder_fn
        self._log_file_path = (
            Path(log_file_path)
            if log_file_path is not None
            else (self._config_store.base_dir / "logs" / "pladaz.log")
        )
        self._ffmpeg_path = ffmpeg_path
        self._cached_ffmpeg_version: Optional[str] = None

    def set_dialog_callbacks(
        self,
        file_dialog_fn: Optional[Callable[[], Optional[str]]] = None,
        folder_dialog_fn: Optional[Callable[[], Optional[str]]] = None,
        exe_dialog_fn: Optional[Callable[[], Optional[str]]] = None,
        quit_fn: Optional[Callable[[], None]] = None,
    ) -> None:
        if file_dialog_fn is not None:
            self._file_dialog_fn = file_dialog_fn
        if folder_dialog_fn is not None:
            self._folder_dialog_fn = folder_dialog_fn
        if exe_dialog_fn is not None:
            self._exe_dialog_fn = exe_dialog_fn
        if quit_fn is not None:
            self._quit_fn = quit_fn

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

    def _get_ffmpeg_version(self) -> str:
        if self._cached_ffmpeg_version is None:
            self._cached_ffmpeg_version = _query_ffmpeg_version(self._ffmpeg_path)
        return self._cached_ffmpeg_version

    def _build_ytdlp_status(self) -> dict[str, Any]:
        ytdlp_path = self._source_adapter.ytdlp_path
        present = ytdlp_path.exists() and ytdlp_path.is_file()
        version = self._source_adapter.get_version(ytdlp_path) if present else None
        if present and not version:
            present = False
        return {
            "present": present,
            "version": version,
            "expected_path": str(ytdlp_path),
        }

    def get_initial_state(self) -> dict[str, Any]:
        try:
            cfg = self._config_store.load_config()
            dest = str(cfg.get("destination_path") or "").strip()
            sd_dto = None
            if dest:
                sd_status = self._sd_card_manager._probe.probe_destination(Path(dest))
                sd_dto = sdcard_status_to_dto(sd_status)
            removable_dtos = [
                sdcard_status_to_dto(d)
                for d in self._sd_card_manager.list_removable_drives()
            ]
            if sd_dto is None and removable_dtos:
                sd_dto = removable_dtos[0]

            ytdlp_info = self._build_ytdlp_status()
            browser_detection = detect_browsers()
            startup_err = (
                structured_error_to_dto(self._config_store.last_error)
                if self._config_store.last_error is not None
                else None
            )

            b_name = cfg.get("browser_cookies_name")
            return {
                "success": True,
                "version": __version__,
                "config": cfg,
                "disclaimer_accepted": bool(cfg.get("disclaimer_accepted", False)),
                "sd_status": sd_dto,
                "removable_drives": removable_dtos,
                "queue": [task_to_dto(t) for t in self._queue_manager.get_tasks()],
                "queue_running": self._queue_manager.is_queue_running(),
                "queue_halted": self._queue_manager.is_queue_halted(),
                "pending_conflict": self._queue_manager.get_pending_conflict(),
                "ytdlp_status": ytdlp_info,
                "browser_detection": browser_detection.to_dict(),
                "browser_cookies": {
                    "enabled": bool(cfg.get("browser_cookies_enabled", False)),
                    "browser": b_name,
                    "browser_label": browser_label(b_name) if b_name else None,
                },
                "system_info": {
                    "version": __version__,
                    "ytdlp_version": ytdlp_info["version"] or "missing",
                    "ffmpeg_version": self._get_ffmpeg_version(),
                    "config_path": str(self._config_store.config_path),
                    "log_path": str(self._log_file_path),
                },
                "startup_error": startup_err,
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

    def scan_storage_devices(self) -> dict[str, Any]:
        """Scan removable drives and probe current destination_path (SYSTEM_DESIGN.md 2.6, Board 03)."""
        try:
            cfg = self._config_store.load_config()
            dest = str(cfg.get("destination_path") or "").strip()
            removable_dtos = [
                sdcard_status_to_dto(d)
                for d in self._sd_card_manager.list_removable_drives()
            ]
            sd_dto = None
            if dest:
                sd_status = self._sd_card_manager._probe.probe_destination(Path(dest))
                sd_dto = sdcard_status_to_dto(sd_status)
                self._queue_manager._events.emit_sdcard_status_changed(sd_status, alert=None)
            elif removable_dtos:
                sd_dto = removable_dtos[0]

            return {
                "success": True,
                "devices": removable_dtos,
                "sd_status": sd_dto,
            }
        except Exception as exc:
            return self._error_response(exc)

    def browse_destination_folder(self) -> dict[str, Any]:
        """Open native folder picker and save destination_path in config.json (SYSTEM_DESIGN.md 2.6, Boards 03 & 06)."""
        try:
            chosen = self._folder_dialog_fn() if self._folder_dialog_fn is not None else None
            if not chosen:
                return {"success": False, "cancelled": True, "selected_path": None}

            target_dir = Path(chosen)
            sd_status = self._sd_card_manager.check_destination(target_dir, required_bytes=0)
            clean_path = str(target_dir)
            cfg = self._config_store.load_config()
            cfg["destination_path"] = clean_path
            self._config_store.save_config(cfg)

            self._queue_manager._events.emit_sdcard_status_changed(sd_status, alert=None)
            return {
                "success": True,
                "selected_path": clean_path,
                "sd_status": sdcard_status_to_dto(sd_status),
                "config": cfg,
            }
        except Exception as exc:
            return self._error_response(exc)

    def select_detected_drive(self, drive_root: str) -> dict[str, Any]:
        """Select a removable drive strictly from the Backend-scanned list and verify writability (Board 03)."""
        try:
            raw_id = (drive_root or "").strip()
            if not raw_id:
                raise SDCardDisconnectedError(
                    message_en="No removable drive identifier provided.",
                )

            norm_requested = os.path.normcase(os.path.normpath(raw_id))
            matched_drive = None
            for d in self._sd_card_manager.list_removable_drives():
                norm_candidate = os.path.normcase(os.path.normpath(d.drive_root))
                if norm_candidate == norm_requested:
                    matched_drive = d
                    break

            if matched_drive is None:
                raise SDCardDisconnectedError(
                    message_en=f"Drive '{raw_id}' is not in the detected removable drives list.",
                )

            target_dir = Path(matched_drive.drive_root)
            sd_status = self._sd_card_manager.check_destination(target_dir, required_bytes=0)
            clean_path = str(target_dir)

            cfg = self._config_store.load_config()
            cfg["destination_path"] = clean_path
            self._config_store.save_config(cfg)

            self._queue_manager._events.emit_sdcard_status_changed(sd_status, alert=None)
            return {
                "success": True,
                "selected_path": clean_path,
                "sd_status": sdcard_status_to_dto(sd_status),
                "config": cfg,
            }
        except Exception as exc:
            return self._error_response(exc)

    def update_config(self, partial: dict[str, Any]) -> dict[str, Any]:
        """Save Settings values. Only keys in UPDATABLE_CONFIG_KEYS are accepted; cookies, disclaimer,
        and destination folder each have their own dedicated method with backend validation."""
        try:
            if not isinstance(partial, dict):
                raise PladazError(
                    code=ErrorCode.ERR_CONFIG_INVALID,
                    message_en="Invalid configuration payload.",
                    recoverable=True,
                )
            for key, value in partial.items():
                expected_type = UPDATABLE_CONFIG_KEYS.get(key)
                if expected_type is None:
                    raise PladazError(
                        code=ErrorCode.ERR_CONFIG_INVALID,
                        message_en=f"Setting '{key}' cannot be changed here.",
                        recoverable=True,
                    )
                if not isinstance(value, expected_type):
                    raise PladazError(
                        code=ErrorCode.ERR_CONFIG_INVALID,
                        message_en=f"Setting '{key}' has an invalid value.",
                        recoverable=True,
                    )
            cfg = self._config_store.load_config()
            sd_dto = None
            if "destination_path" in partial and partial["destination_path"]:
                candidate_dest = Path(str(partial["destination_path"]).strip())
                sd_status = self._sd_card_manager.check_destination(candidate_dest, required_bytes=0)
                sd_dto = sdcard_status_to_dto(sd_status)
                partial = dict(partial)
                partial["destination_path"] = str(candidate_dest)

            cfg.update(partial)
            self._config_store.save_config(cfg)
            dest = str(cfg.get("destination_path") or "").strip()
            if dest:
                sd_status = self._sd_card_manager._probe.probe_destination(Path(dest))
                sd_dto = sdcard_status_to_dto(sd_status)
                if "destination_path" in partial:
                    self._queue_manager._events.emit_sdcard_status_changed(sd_status, alert=None)
            return {"success": True, "config": cfg, "sd_status": sd_dto}
        except Exception as exc:
            return self._error_response(exc)

    def select_cookies_file(self) -> dict[str, Any]:
        """Open native file picker to select Netscape cookies.txt (SYSTEM_DESIGN.md 2.6, Board 06)."""
        try:
            chosen = self._file_dialog_fn() if self._file_dialog_fn is not None else None
            if not chosen:
                return {"success": False, "cancelled": True, "selected_path": None}

            cookies_path = Path(chosen)
            if not cookies_path.exists() or not cookies_path.is_file():
                raise SourceExtractionError(
                    message_en="Selected cookies.txt file does not exist.",
                )

            clean_str = str(cookies_path)
            cfg = self._config_store.load_config()
            cfg["cookies_file_path"] = clean_str
            self._config_store.save_config(cfg)
            return {
                "success": True,
                "selected_path": clean_str,
                "filename": cookies_path.name,
            }
        except Exception as exc:
            return self._error_response(exc)

    def clear_cookies_file(self) -> dict[str, Any]:
        """Explicitly clear cookies_file_path in config.json without implicit empty-string arguments (Board 06)."""
        try:
            cfg = self._config_store.load_config()
            cfg["cookies_file_path"] = None
            self._config_store.save_config(cfg)
            return {
                "success": True,
                "selected_path": None,
                "filename": None,
            }
        except Exception as exc:
            return self._error_response(exc)

    def detect_supported_browsers(self) -> dict[str, Any]:
        """Detect supported installed browsers on the host system without reading cookie contents."""
        try:
            result = detect_browsers()
            cfg = self._config_store.load_config()
            configured_browser = cfg.get("browser_cookies_name")
            return {
                "success": True,
                "detection": result.to_dict(),
                "configured_browser": configured_browser,
                "configured_label": browser_label(configured_browser) if configured_browser else None,
                "enabled": bool(cfg.get("browser_cookies_enabled", False)),
            }
        except Exception as exc:
            return self._error_response(exc)

    def test_browser_cookies(self, browser: str) -> dict[str, Any]:
        """Test whether yt-dlp can access cookies from the specified browser without downloading."""
        try:
            norm_name = (browser or "").strip().lower()
            if not is_supported_browser(norm_name):
                raise PladazError(
                    code=ErrorCode.ERR_CONFIG_INVALID,
                    message_en=f"Unsupported browser '{browser}'. Supported: chrome, firefox, edge, brave, opera, vivaldi, chromium.",
                    recoverable=True,
                )
            check = self._source_adapter.check_browser_cookies(norm_name)
            return {
                "success": check.readable,
                "browser": norm_name,
                "browser_label": browser_label(norm_name),
                "check": check.to_dict(),
                "error": None if check.readable else {
                    "code": ErrorCode.ERR_BROWSER_COOKIES_FAILED,
                    "message_en": f"{check.message} {check.next_step}".strip(),
                    "recoverable": True,
                },
            }
        except Exception as exc:
            return self._error_response(exc)

    def select_browser_cookies(self, browser: str) -> dict[str, Any]:
        """Confirm user consent, test cookie access, and persist the choice in config.json."""
        try:
            norm_name = (browser or "").strip().lower()
            if not is_supported_browser(norm_name):
                raise PladazError(
                    code=ErrorCode.ERR_CONFIG_INVALID,
                    message_en=f"Unsupported browser '{browser}'. Supported: chrome, firefox, edge, brave, opera, vivaldi, chromium.",
                    recoverable=True,
                )
            check = self._source_adapter.check_browser_cookies(norm_name)
            cfg = self._config_store.load_config()
            cfg["browser_cookies_name"] = norm_name
            cfg["browser_cookies_enabled"] = bool(check.readable)
            self._config_store.save_config(cfg)
            return {
                "success": check.readable,
                "browser": norm_name,
                "browser_label": browser_label(norm_name),
                "check": check.to_dict(),
                "config": cfg,
                "error": None if check.readable else {
                    "code": ErrorCode.ERR_BROWSER_COOKIES_FAILED,
                    "message_en": f"{check.message} {check.next_step}".strip(),
                    "recoverable": True,
                },
            }
        except Exception as exc:
            return self._error_response(exc)

    def clear_browser_cookies(self) -> dict[str, Any]:
        """Disable Browser Authentication in config.json."""
        try:
            cfg = self._config_store.load_config()
            cfg["browser_cookies_enabled"] = False
            cfg["browser_cookies_name"] = None
            self._config_store.save_config(cfg)
            return {
                "success": True,
                "browser": None,
                "browser_label": None,
                "enabled": False,
                "config": cfg,
            }
        except Exception as exc:
            return self._error_response(exc)

    def check_ytdlp_status(self) -> dict[str, Any]:
        """Check whether standalone yt-dlp.exe exists and responds to --version (Board 09)."""
        try:
            status = self._build_ytdlp_status()
            return {"success": True, **status}
        except Exception as exc:
            return self._error_response(exc)

    def locate_ytdlp_file(self) -> dict[str, Any]:
        """Allow user to select an existing yt-dlp.exe via native file dialog and copy it to the expected location (Board 09)."""
        try:
            chosen = self._exe_dialog_fn() if self._exe_dialog_fn is not None else None
            if not chosen:
                return {"success": False, "cancelled": True}

            src_path = Path(chosen)
            if not src_path.exists() or not src_path.is_file():
                raise SourceExtractionError(
                    message_en=f"Selected file does not exist: '{src_path}'.",
                )

            version = self._source_adapter.get_version(src_path)
            if not version:
                raise SourceExtractionError(
                    message_en="Selected executable is not a valid yt-dlp.exe binary ('--version' check failed).",
                )

            target_path = self._source_adapter.ytdlp_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if src_path.resolve() != target_path.resolve():
                tmp_path = target_path.with_name(f"{target_path.stem}.locate-tmp{target_path.suffix}")
                shutil.copy2(src_path, tmp_path)
                os.replace(tmp_path, target_path)

            return {
                "success": True,
                "present": True,
                "version": version,
                "expected_path": str(target_path),
            }
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
        """Add one link per line. A bad line does not stop the others: tracks from good lines are queued
        and reported in `tasks_added`, and each bad line is listed in `failed_lines` (UX-11)."""
        lines = [
            line.strip()
            for line in (url_text or "").splitlines()
            if line.strip()
        ] or [(url_text or "").strip()]
        added_all = []
        failed_lines: list[dict[str, Any]] = []
        for url in lines:
            try:
                added_all.extend(self._queue_manager.enqueue_url(url))
            except Exception as exc:
                failed_lines.append({"url": url, "error": self._error_response(exc)["error"]})
        return {
            "success": not failed_lines,
            "tasks_added": [task_to_dto(t) for t in added_all],
            "failed_lines": failed_lines,
            "error": failed_lines[0]["error"] if failed_lines else None,
        }

    def start_queue(self) -> dict[str, Any]:
        try:
            self._queue_manager.start_queue(background=True)
            return {
                "success": True,
                "queue_running": self._queue_manager.is_queue_running(),
                "queue_halted": self._queue_manager.is_queue_halted(),
            }
        except Exception as exc:
            return self._error_response(exc)

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        try:
            ok = self._queue_manager.cancel_task(task_id)
            if not ok:
                return {
                    "success": False,
                    "queue_running": self._queue_manager.is_queue_running(),
                    "queue_halted": self._queue_manager.is_queue_halted(),
                    "error": {
                        "code": ErrorCode.ERR_TASK_CANCELLED,
                        "message_en": "Task could not be cancelled (already finished or not found).",
                        "recoverable": True,
                    },
                }
            return {
                "success": True,
                "queue_running": self._queue_manager.is_queue_running(),
                "queue_halted": self._queue_manager.is_queue_halted(),
            }
        except Exception as exc:
            return self._error_response(exc)

    def resume_queue(self) -> dict[str, Any]:
        try:
            self._queue_manager.resume_queue(background=True)
            return {
                "success": True,
                "queue_running": self._queue_manager.is_queue_running(),
                "queue_halted": self._queue_manager.is_queue_halted(),
            }
        except Exception as exc:
            return self._error_response(exc)

    def resolve_conflict(
        self,
        task_id: str,
        action: str,
        scope: str = "single",
    ) -> dict[str, Any]:
        try:
            ok = self._queue_manager.resolve_conflict(
                task_id=task_id,
                action=ConflictAction(action),
                scope=ConflictScope(scope),
            )
            if not ok:
                return {
                    "success": False,
                    "error": {
                        "code": ErrorCode.ERR_CONFLICT_NOT_FOUND,
                        "message_en": "No active conflict prompt found for the specified task.",
                        "recoverable": True,
                    },
                }
            return {"success": True}
        except Exception as exc:
            return self._error_response(exc)

    def retry_task(self, task_id: str) -> dict[str, Any]:
        try:
            task = self._queue_manager.retry(task_id)
            if task is None:
                return {
                    "success": False,
                    "task": None,
                    "error": {
                        "code": ErrorCode.ERR_TASK_RETRY_FAILED,
                        "message_en": "Task cannot be retried (not found or not in Failed state).",
                        "recoverable": True,
                    },
                }
            return {"success": True, "task": task_to_dto(task)}
        except Exception as exc:
            return self._error_response(exc)

    def remove_task(self, task_id: str) -> dict[str, Any]:
        try:
            ok = self._queue_manager.remove(task_id)
            if not ok:
                return {
                    "success": False,
                    "error": {
                        "code": ErrorCode.ERR_TASK_REMOVE_FAILED,
                        "message_en": "Task cannot be removed while downloading or was not found.",
                        "recoverable": True,
                    },
                }
            return {"success": True}
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

    def clear_history(self) -> dict[str, Any]:
        """Clear all history entries in history.json (Board 07)."""
        try:
            self._config_store.clear_history()
            return {"success": True, "entries": []}
        except Exception as exc:
            return self._error_response(exc)

    def get_cover_preview(self, task_id: str) -> dict[str, Any]:
        """Return Base64 JPEG Data URL for task cover art (SYSTEM_DESIGN.md 2.6)."""
        try:
            data_url = self._queue_manager.get_cover_data_url(task_id)
            return {"success": True, "task_id": task_id, "data_url": data_url}
        except Exception as exc:
            return self._error_response(exc)

    def get_recent_logs(self, max_lines: int = 80) -> dict[str, Any]:
        """Read recent sanitized lines from pladaz.log for Board 17 (Error Log modal)."""
        try:
            lines: list[str] = []
            if self._log_file_path.exists():
                raw_text = self._log_file_path.read_text(encoding="utf-8", errors="replace")
                all_lines = raw_text.splitlines()
                tail = all_lines[-max(1, int(max_lines)) :]
                lines = [redact_sensitive_text(line) or "" for line in tail]
            return {
                "success": True,
                "lines": lines,
                "log_path": str(self._log_file_path),
            }
        except Exception as exc:
            return self._error_response(exc)

    def open_folder(self, target: str = "destination") -> dict[str, Any]:
        """Open destination folder on SD Card or logs folder in Windows Explorer (Boards 15, 17, 20)."""
        try:
            if target == "logs":
                folder = self._log_file_path.parent
                folder.mkdir(parents=True, exist_ok=True)
            else:
                cfg = self._config_store.load_config()
                dest_str = str(cfg.get("destination_path") or "").strip()
                if not dest_str:
                    return {
                        "success": False,
                        "error": {
                            "code": ErrorCode.ERR_SDCARD_DISCONNECTED,
                            "message_en": "No destination folder configured.",
                            "recoverable": True,
                        },
                    }
                folder = Path(dest_str)
                if not folder.exists():
                    return {
                        "success": False,
                        "error": {
                            "code": ErrorCode.ERR_SDCARD_DISCONNECTED,
                            "message_en": f"Folder does not exist on card: '{folder}'.",
                            "recoverable": True,
                        },
                    }

            if self._open_folder_fn is not None:
                self._open_folder_fn(folder)
            elif os.name == "nt":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            return {"success": True, "opened_path": str(folder)}
        except Exception as exc:
            return self._error_response(exc)

    def quit_app(self) -> dict[str, Any]:
        """Close the application window (Board 04 QUIT button)."""
        try:
            if self._quit_fn is not None:
                self._quit_fn()
            return {"success": True}
        except Exception as exc:
            return self._error_response(exc)
