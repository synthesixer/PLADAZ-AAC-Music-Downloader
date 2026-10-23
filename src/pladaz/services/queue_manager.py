"""DownloadQueueManager service implementing Sequential Worker, 9-step Pipeline, Conflict Resolution, and SD Card Watcher (SYSTEM_DESIGN.md 3.1-3.6, DEC-023, DEC-036, DEC-039..044)."""

from datetime import datetime, timezone
from pathlib import Path
import shutil
from threading import Event, Lock, Thread
import time
from typing import Optional
import uuid

from pladaz.bridge.events import EventDispatcher
from pladaz.domain.enums import (
    ConflictAction,
    ConflictScope,
    Stage,
    TaskStatus,
)
from pladaz.domain.errors import (
    ErrorCode,
    PathTooLongError,
    PladazError,
    SDCardDisconnectedError,
    SDCardInsufficientSpaceError,
    TaskCancelledError,
)
from pladaz.domain.models import HistoryEntry, StructuredError, TrackTask
from pladaz.services.audio_processor import AudioProcessingService
from pladaz.services.config_store import (
    CONFIG_KEY_REQUIRE_ALBUM_ART,
    ConfigHistoryStore,
)
from pladaz.services.folder_organizer import SmartFolderOrganizer
from pladaz.services.logger import PladazLogger, build_safe_structured_error
from pladaz.services.metadata_service import MetadataAlbumArtService
from pladaz.services.output_validator import OutputValidator
from pladaz.services.sd_card_manager import SDCardManager
from pladaz.services.source_adapter import DownloadSourceAdapter, validate_youtube_url

# Confirmed by user in Phase 3 pre-start Q3 (DEC-041): default periodic SD card check interval is 2.0 seconds
DEFAULT_SD_POLL_INTERVAL_SEC: float = 2.0


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DownloadQueueManager:
    """Manages the sequential download queue, conflict prompts, Apply-to-all scopes, and periodic SD card monitoring."""

    def __init__(
        self,
        source_adapter: DownloadSourceAdapter,
        metadata_service: MetadataAlbumArtService,
        folder_organizer: SmartFolderOrganizer,
        audio_processor: AudioProcessingService,
        output_validator: OutputValidator,
        sd_card_manager: SDCardManager,
        config_store: ConfigHistoryStore,
        event_dispatcher: EventDispatcher,
        temp_root: Path,
        logger: Optional[PladazLogger] = None,
        sd_poll_interval_sec: float = DEFAULT_SD_POLL_INTERVAL_SEC,
        clean_temp_on_init: bool = True,
    ) -> None:
        self._source_adapter = source_adapter
        self._metadata_service = metadata_service
        self._folder_organizer = folder_organizer
        self._audio_processor = audio_processor
        self._output_validator = output_validator
        self._sd_card_manager = sd_card_manager
        self._config_store = config_store
        self._events = event_dispatcher
        self.temp_root = Path(temp_root)
        self._logger = logger
        self.sd_poll_interval_sec = sd_poll_interval_sec

        self._lock = Lock()
        self._tasks: list[TrackTask] = []

        # Queue worker state (DEC-042: starts idle until start_queue() is called)
        self._worker_active: bool = False
        self._queue_halted: bool = False
        self._worker_thread: Optional[Thread] = None
        self._idle_event = Event()
        self._idle_event.set()

        # Per-task cancellation and conflict-wait synchronization
        self._cancel_events: dict[str, Event] = {}
        self._sd_disconnected_flags: dict[str, bool] = {}
        self._conflict_events: dict[str, Event] = {}
        self._conflict_resolutions: dict[str, ConflictAction] = {}
        self._pending_conflict_album_keys: dict[str, str] = {}

        # In-memory Apply-to-all rules (DEC-044: never persisted to config.json)
        self._album_conflict_rules: dict[str, ConflictAction] = {}
        self._queue_conflict_rule: Optional[ConflictAction] = None

        self.temp_root.mkdir(parents=True, exist_ok=True)
        if clean_temp_on_init:
            self.cleanup_all_temp()

    def cleanup_all_temp(self) -> None:
        """Clean up any leftover files or task subdirectories in `temp_root` on startup (SYSTEM_DESIGN.md 3.6)."""
        if not self.temp_root.exists():
            return
        for child in self.temp_root.iterdir():
            try:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            except OSError:
                pass

    def get_tasks(self) -> list[TrackTask]:
        """Return a snapshot list of tasks currently in the queue."""
        with self._lock:
            return list(self._tasks)

    def get_task(self, task_id: str) -> Optional[TrackTask]:
        with self._lock:
            for t in self._tasks:
                if t.task_id == task_id:
                    return t
        return None

    def _get_cookies_path(self) -> Optional[Path]:
        cfg = self._config_store.load_config()
        raw_cookies = cfg.get("cookies_file_path")
        if raw_cookies and isinstance(raw_cookies, str) and raw_cookies.strip():
            p = Path(raw_cookies.strip())
            if p.exists():
                return p
        return None

    def _get_destination_root(self) -> Path:
        cfg = self._config_store.load_config()
        dest_str = str(cfg.get("destination_path") or "").strip()
        if not dest_str:
            raise SDCardDisconnectedError(
                message_en="No destination folder selected on Micro SD Card.",
                details="destination_path is empty",
            )
        return Path(dest_str)

    def _get_require_cover(self) -> bool:
        cfg = self._config_store.load_config()
        return bool(cfg.get(CONFIG_KEY_REQUIRE_ALBUM_ART, False))

    def enqueue_url(self, url: str) -> list[TrackTask]:
        """Extract entries from a Single / Playlist / Album URL and add them as Queued tasks (DEC-025, DEC-042).

        Does NOT start downloading automatically if the queue worker has not been started.
        """
        clean_url = validate_youtube_url(url)
        cookies_path = self._get_cookies_path()
        entries = self._source_adapter.extract_entries(clean_url, cookies_path=cookies_path)

        added_tasks: list[TrackTask] = []
        with self._lock:
            for entry in entries:
                task_id = f"task-{uuid.uuid4().hex[:12]}"
                task = TrackTask(
                    task_id=task_id,
                    entry_url=entry.entry_url,
                    batch_id=entry.batch_id,
                    status=TaskStatus.QUEUED,
                    stage=None,
                    progress_percent=0.0,
                )
                self._tasks.append(task)
                self._cancel_events[task_id] = Event()
                added_tasks.append(task)
            snapshot = list(self._tasks)

        self._events.emit_queue_updated(snapshot)
        return added_tasks

    def start_queue(self, background: bool = True) -> None:
        """Start processing `Queued` tasks sequentially (DEC-042)."""
        with self._lock:
            self._queue_halted = False
            if self._worker_active:
                return
            self._worker_active = True
            self._idle_event.clear()

        if background:
            t = Thread(
                target=self._worker_loop,
                name="PladazQueueWorker",
                daemon=True,
            )
            self._worker_thread = t
            t.start()
        else:
            self._worker_loop()

    def resume_queue(self, background: bool = True) -> None:
        """Resume queue processing after an SD Card disconnect or space error once the card is ready (DEC-042)."""
        dest_root = self._get_destination_root()
        status = self._sd_card_manager.check_destination(dest_root, required_bytes=0)
        self._events.emit_sdcard_status_changed(status, alert=None)
        self.start_queue(background=background)

    def wait_for_idle(self, timeout: float = 30.0) -> bool:
        """Wait until the sequential worker finishes or halts."""
        return self._idle_event.wait(timeout=timeout)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a Queued or Downloading task -> sets Failed with ERR_TASK_CANCELLED and cleans Temp (DEC-042, TC-016)."""
        with self._lock:
            target_task: Optional[TrackTask] = None
            for t in self._tasks:
                if t.task_id == task_id:
                    target_task = t
                    break
            if target_task is None:
                return False

            if target_task.status == TaskStatus.QUEUED:
                target_task.status = TaskStatus.FAILED
                target_task.stage = None
                target_task.error = StructuredError(
                    code=ErrorCode.ERR_TASK_CANCELLED,
                    message_en="Task was cancelled by the user.",
                    recoverable=True,
                    task_id=task_id,
                )
                cancel_ev = self._cancel_events.get(task_id)
                if cancel_ev:
                    cancel_ev.set()
                self._cleanup_task_temp_dir(task_id)
                self._record_history_entry(target_task)
                self._check_and_reset_queue_scope_unlocked()
                queued_cancelled = True
            elif target_task.status == TaskStatus.DOWNLOADING:
                cancel_ev = self._cancel_events.setdefault(task_id, Event())
                cancel_ev.set()
                conflict_ev = self._conflict_events.get(task_id)
                if conflict_ev:
                    conflict_ev.set()
                queued_cancelled = False
            else:
                return False

        if queued_cancelled and target_task is not None:
            self._events.emit_task_status_changed(target_task)
        return True

    def retry(self, task_id: str) -> Optional[TrackTask]:
        """Transition a Failed task back to Queued so it can be processed again (SYSTEM_DESIGN.md 3.2)."""
        with self._lock:
            for t in self._tasks:
                if t.task_id == task_id and t.status == TaskStatus.FAILED:
                    t.status = TaskStatus.QUEUED
                    t.stage = None
                    t.progress_percent = 0.0
                    t.error = None
                    t.warnings.clear()
                    self._cancel_events[task_id] = Event()
                    self._sd_disconnected_flags.pop(task_id, None)
                    snapshot = list(self._tasks)
                    break
            else:
                return None

        self._events.emit_task_status_changed(t)
        self._events.emit_queue_updated(snapshot)
        return t

    def remove(self, task_id: str) -> bool:
        """Remove a non-downloading task from the queue."""
        with self._lock:
            for idx, t in enumerate(self._tasks):
                if t.task_id == task_id:
                    if t.status == TaskStatus.DOWNLOADING:
                        return False
                    self._tasks.pop(idx)
                    self._cancel_events.pop(task_id, None)
                    self._check_and_reset_queue_scope_unlocked()
                    snapshot = list(self._tasks)
                    break
            else:
                return False

        self._events.emit_queue_updated(snapshot)
        return True

    def clear_completed_tasks(self) -> None:
        """Remove all Completed tasks from the queue."""
        with self._lock:
            self._tasks = [
                t for t in self._tasks if t.status != TaskStatus.COMPLETED
            ]
            self._check_and_reset_queue_scope_unlocked()
            snapshot = list(self._tasks)
        self._events.emit_queue_updated(snapshot)

    def resolve_conflict(
        self,
        task_id: str,
        action: ConflictAction | str,
        scope: ConflictScope | str = ConflictScope.SINGLE,
    ) -> None:
        """Resolve a pending destination file conflict and optionally store an Apply-to-all rule (DEC-019, DEC-044)."""
        resolved_action = (
            action if isinstance(action, ConflictAction) else ConflictAction(action)
        )
        resolved_scope = (
            scope if isinstance(scope, ConflictScope) else ConflictScope(scope)
        )

        with self._lock:
            self._conflict_resolutions[task_id] = resolved_action
            album_key = self._pending_conflict_album_keys.get(task_id)

            if resolved_scope == ConflictScope.ALBUM and album_key:
                # DEC-044: Apply to all in this album matches tasks with the same sanitized <Album Artist>/<Album> folder
                self._album_conflict_rules[album_key] = resolved_action
            elif resolved_scope == ConflictScope.QUEUE:
                # DEC-044: Apply to all in queue applies to all tasks in the current queue run until the queue becomes empty
                self._queue_conflict_rule = resolved_action

            ev = self._conflict_events.get(task_id)
            if ev is not None:
                ev.set()

    def _check_and_reset_queue_scope_unlocked(self) -> None:
        """Reset `Apply to all in queue` rule when no Queued or Downloading tasks remain (DEC-044)."""
        has_active_or_queued = any(
            t.status in (TaskStatus.QUEUED, TaskStatus.DOWNLOADING)
            for t in self._tasks
        )
        if not has_active_or_queued:
            self._queue_conflict_rule = None
            self._album_conflict_rules.clear()

    def _next_queued_task(self) -> Optional[TrackTask]:
        with self._lock:
            if self._queue_halted:
                return None
            for t in self._tasks:
                if t.status == TaskStatus.QUEUED:
                    return t
            return None

    def _worker_loop(self) -> None:
        try:
            while True:
                task = self._next_queued_task()
                if task is None:
                    break
                self._process_single_task(task)
        finally:
            with self._lock:
                self._worker_active = False
                self._check_and_reset_queue_scope_unlocked()
                self._idle_event.set()

    def _set_task_stage(self, task: TrackTask, stage: Stage) -> None:
        task.stage = stage
        self._events.emit_task_progress(
            task_id=task.task_id,
            stage=stage,
            progress_percent=task.progress_percent,
        )

    def _cleanup_task_temp_dir(self, task_id: str) -> None:
        task_temp_dir = self.temp_root / task_id
        if task_temp_dir.exists():
            shutil.rmtree(task_temp_dir, ignore_errors=True)

    def _record_history_entry(self, task: TrackTask) -> None:
        if task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            return
        meta = task.metadata
        entry = HistoryEntry(
            task_id=task.task_id,
            finished_at=_iso_now(),
            status=task.status,
            title=meta.title if meta else None,
            album_artist=meta.album_artist if meta else None,
            album=meta.album if meta else None,
            target_file_path=str(task.target_file_path) if task.target_file_path else None,
            source_url=task.entry_url,
            warnings=list(task.warnings),
            error_code=task.error.code if task.error else None,
        )
        try:
            self._config_store.append_history(entry)
        except Exception as exc:
            if self._logger:
                self._logger.error(
                    component="DownloadQueueManager",
                    message=f"Failed to append history entry: {exc}",
                    task_id=task.task_id,
                )

    def _start_sd_watcher(
        self,
        task_id: str,
        dest_root: Path,
        stop_watcher_ev: Event,
        cancel_ev: Event,
    ) -> Thread:
        """Start a periodic background watcher checking `SDCardManager.is_card_present` during task execution (DEC-041)."""

        def _watch() -> None:
            while not stop_watcher_ev.wait(timeout=self.sd_poll_interval_sec):
                if not self._sd_card_manager.is_card_present(dest_root):
                    with self._lock:
                        self._sd_disconnected_flags[task_id] = True
                        conflict_ev = self._conflict_events.get(task_id)
                        if conflict_ev:
                            conflict_ev.set()
                    cancel_ev.set()
                    break

        watcher = Thread(
            target=_watch,
            name=f"SDCardWatcher-{task_id}",
            daemon=True,
        )
        watcher.start()
        return watcher

    def _check_interrupted(self, task_id: str, cancel_ev: Event) -> None:
        if self._sd_disconnected_flags.get(task_id):
            raise SDCardDisconnectedError(
                message_en="Micro SD Card was removed during task processing.",
                task_id=task_id,
            )
        if cancel_ev.is_set():
            raise TaskCancelledError(task_id=task_id)

    def _process_single_task(self, task: TrackTask) -> None:
        """Execute the strict 9-step per-track pipeline (SYSTEM_DESIGN.md 3.1, DEC-036, DEC-039..044)."""
        task_id = task.task_id
        task_temp_dir = self.temp_root / task_id
        task_temp_dir.mkdir(parents=True, exist_ok=True)

        with self._lock:
            cancel_ev = self._cancel_events.setdefault(task_id, Event())
            if cancel_ev.is_set():
                task.status = TaskStatus.FAILED
                task.stage = None
                task.error = StructuredError(
                    code=ErrorCode.ERR_TASK_CANCELLED,
                    message_en="Task was cancelled by the user.",
                    recoverable=True,
                    task_id=task_id,
                )
                self._cleanup_task_temp_dir(task_id)
                self._record_history_entry(task)
                self._events.emit_task_status_changed(task)
                return

            task.status = TaskStatus.DOWNLOADING
            task.stage = Stage.CHECKING_SD
            task.progress_percent = 0.0

        self._events.emit_task_status_changed(task)

        stop_watcher_ev = Event()
        watcher_thread: Optional[Thread] = None

        try:
            # Step 1: checking_sd
            self._set_task_stage(task, Stage.CHECKING_SD)
            dest_root = self._get_destination_root()
            self._sd_card_manager.check_destination(dest_root, required_bytes=0)
            self._check_interrupted(task_id, cancel_ev)

            # Start periodic SD card watcher while downloading/processing (DEC-041)
            watcher_thread = self._start_sd_watcher(
                task_id=task_id,
                dest_root=dest_root,
                stop_watcher_ev=stop_watcher_ev,
                cancel_ev=cancel_ev,
            )

            # Step 2: fetching_info
            self._set_task_stage(task, Stage.FETCHING_INFO)
            cookies_path = self._get_cookies_path()
            raw_info = self._source_adapter.fetch_track_info(
                task.entry_url, cookies_path=cookies_path
            )
            self._check_interrupted(task_id, cancel_ev)

            # Step 3: resolving_metadata
            self._set_task_stage(task, Stage.RESOLVING_METADATA)
            meta = self._metadata_service.resolve_metadata(
                raw_info, warnings_out=task.warnings
            )
            task.metadata = meta
            self._check_interrupted(task_id, cancel_ev)

            # Step 4: build_target_path & MAX_PATH check (> 259 chars -> ERR_PATH_TOO_LONG BEFORE audio download, DEC-043)
            target_path = self._folder_organizer.build_target_path(dest_root, meta)
            task.target_file_path = target_path

            # Step 5: checking_duplicate & conflict resolution BEFORE audio download (DEC-036)
            self._set_task_stage(task, Stage.CHECKING_DUPLICATE)
            overwrite_flag = False
            if self._folder_organizer.check_conflict(target_path):
                album_key = str(target_path.parent)
                chosen_action = self._get_or_wait_conflict_action(
                    task=task,
                    target_path=target_path,
                    album_key=album_key,
                    cancel_ev=cancel_ev,
                )
                self._check_interrupted(task_id, cancel_ev)

                if chosen_action == ConflictAction.SKIP:
                    # DEC-039 & TC-013: Remove skipped task from queue immediately; do NOT download audio or log history
                    with self._lock:
                        self._tasks = [
                            t for t in self._tasks if t.task_id != task_id
                        ]
                        self._cancel_events.pop(task_id, None)
                        self._conflict_events.pop(task_id, None)
                        self._conflict_resolutions.pop(task_id, None)
                        self._pending_conflict_album_keys.pop(task_id, None)
                        snapshot = list(self._tasks)
                    if self._logger:
                        self._logger.info(
                            component="DownloadQueueManager",
                            message="Task skipped by conflict resolution and removed from queue.",
                            task_id=task_id,
                            stage=Stage.CHECKING_DUPLICATE,
                        )
                    self._events.emit_queue_updated(snapshot)
                    return

                if chosen_action == ConflictAction.KEEP_BOTH:
                    target_path = self._folder_organizer.keep_both_path(target_path)
                    task.target_file_path = target_path
                    overwrite_flag = False
                elif chosen_action == ConflictAction.OVERWRITE:
                    overwrite_flag = True

            self._check_interrupted(task_id, cancel_ev)

            # Step 6a: downloading_stream into Temp
            self._set_task_stage(task, Stage.DOWNLOADING_STREAM)
            stream_plan = self._source_adapter.plan_stream(raw_info)

            def _on_dl_progress(pct: float, speed_str: str, eta_str: str) -> None:
                task.progress_percent = pct
                self._events.emit_task_progress(
                    task_id=task_id,
                    stage=Stage.DOWNLOADING_STREAM,
                    progress_percent=pct,
                    speed_str=speed_str,
                    eta_str=eta_str,
                )

            raw_audio_file = self._source_adapter.download_stream(
                entry_url=task.entry_url,
                plan=stream_plan,
                temp_dir=task_temp_dir,
                progress_cb=_on_dl_progress,
                cancel_event=cancel_ev,
                cookies_path=cookies_path,
            )
            self._check_interrupted(task_id, cancel_ev)

            # Step 6b: processing_audio (FFmpeg remux or encode to M4A)
            self._set_task_stage(task, Stage.PROCESSING_AUDIO)
            temp_m4a_path = task_temp_dir / "processed.m4a"
            task.temp_file_path = temp_m4a_path
            self._audio_processor.to_m4a(
                input_path=raw_audio_file,
                output_path=temp_m4a_path,
                mode=stream_plan.mode,
                cancel_event=cancel_ev,
            )
            self._check_interrupted(task_id, cancel_ev)

            # Step 6c: tagging
            self._set_task_stage(task, Stage.TAGGING)
            self._metadata_service.write_m4a_tags(temp_m4a_path, meta)
            self._check_interrupted(task_id, cancel_ev)

            # Step 6d & Step 7: validating with OutputValidator BEFORE copying to SD Card
            self._set_task_stage(task, Stage.VALIDATING)
            require_cover = self._get_require_cover()
            val_result = self._output_validator.validate(
                temp_m4a_path,
                require_cover=require_cover,
            )
            if not val_result.is_valid:
                err_code = (
                    val_result.error_code or ErrorCode.ERR_VALIDATOR_CORRUPT_FILE
                )
                raise PladazError(
                    code=err_code,
                    message_en=f"Output validation failed ({err_code}). File was not copied to Micro SD Card.",
                    recoverable=False,
                    task_id=task_id,
                )

            for w in val_result.warnings:
                if w not in task.warnings:
                    task.warnings.append(w)

            self._check_interrupted(task_id, cancel_ev)

            # Step 8: copying (Copy & Verify to SD Card; Overwrite uses .pladaz-tmp + os.replace per DEC-040)
            self._set_task_stage(task, Stage.COPYING)
            final_sd_path = self._sd_card_manager.copy_and_verify(
                temp_file=temp_m4a_path,
                target=target_path,
                overwrite=overwrite_flag,
            )
            task.target_file_path = final_sd_path

            # Step 9: Completed
            task.status = TaskStatus.COMPLETED
            task.stage = None
            task.progress_percent = 100.0
            task.temp_file_path = None
            self._record_history_entry(task)
            if self._logger:
                self._logger.info(
                    component="DownloadQueueManager",
                    message=f"Task completed: {final_sd_path}",
                    task_id=task_id,
                )
            self._events.emit_task_status_changed(task)

        except Exception as exc:
            self._handle_task_exception(task, exc)
        finally:
            stop_watcher_ev.set()
            if watcher_thread is not None:
                watcher_thread.join(timeout=1.0)
            self._cleanup_task_temp_dir(task_id)
            task.temp_file_path = None

    def _get_or_wait_conflict_action(
        self,
        task: TrackTask,
        target_path: Path,
        album_key: str,
        cancel_ev: Event,
    ) -> ConflictAction:
        """Return remembered Apply-to-all action or emit `task:conflict_prompt` and wait for user decision (DEC-019, DEC-044)."""
        task_id = task.task_id
        with self._lock:
            if self._queue_conflict_rule is not None:
                return self._queue_conflict_rule
            if album_key in self._album_conflict_rules:
                return self._album_conflict_rules[album_key]

            conflict_ev = Event()
            self._conflict_events[task_id] = conflict_ev
            self._pending_conflict_album_keys[task_id] = album_key
            task.stage = Stage.WAITING_CONFLICT

        meta = task.metadata
        self._events.emit_task_status_changed(task)
        self._events.emit_task_conflict_prompt(
            task_id=task_id,
            existing_path=str(target_path),
            metadata_summary={
                "title": meta.title if meta else "",
                "album_artist": meta.album_artist if meta else None,
                "album": meta.album if meta else None,
            },
        )

        # Wait until user calls resolve_conflict(), or task is cancelled / SD card disconnects
        conflict_ev.wait()
        self._check_interrupted(task_id, cancel_ev)

        with self._lock:
            action = self._conflict_resolutions.pop(task_id, None)
            self._conflict_events.pop(task_id, None)
            self._pending_conflict_album_keys.pop(task_id, None)

        if action is None:
            raise TaskCancelledError(task_id=task_id)
        return action

    def _handle_task_exception(self, task: TrackTask, exc: Exception) -> None:
        task_id = task.task_id
        current_stage = task.stage

        # If periodic SD card watcher detected a disconnect, override TaskCancelledError with SDCardDisconnectedError
        if self._sd_disconnected_flags.get(task_id) and not isinstance(
            exc, SDCardDisconnectedError
        ):
            exc = SDCardDisconnectedError(
                message_en="Micro SD Card was removed during task processing.",
                task_id=task_id,
            )

        if isinstance(exc, (SDCardDisconnectedError, SDCardInsufficientSpaceError)):
            with self._lock:
                self._queue_halted = True
            structured = build_safe_structured_error(
                code=exc.code,
                message_en=exc.message_en,
                recoverable=True,
                task_id=task_id,
                details=exc.structured.details,
            )
            try:
                dest_str = str(
                    self._config_store.load_config().get("destination_path") or ""
                )
                sd_status = self._sd_card_manager._probe.probe_destination(
                    Path(dest_str) if dest_str else Path(".")
                )
            except Exception:
                from pladaz.domain.models import SDCardStatus

                sd_status = SDCardStatus(
                    drive_root="",
                    destination_dir="",
                    is_connected=False,
                    is_writable=False,
                    free_bytes=0,
                    total_bytes=0,
                )
            self._events.emit_sdcard_status_changed(sd_status, alert=structured)
        elif isinstance(exc, PladazError):
            structured = build_safe_structured_error(
                code=exc.code,
                message_en=exc.message_en,
                recoverable=exc.recoverable,
                task_id=task_id,
                details=exc.structured.details,
            )
        else:
            structured = build_safe_structured_error(
                code=ErrorCode.ERR_SOURCE_EXTRACTION_FAILED,
                message_en="An unexpected error occurred while processing the track.",
                recoverable=False,
                task_id=task_id,
                details=str(exc),
            )

        task.status = TaskStatus.FAILED
        task.stage = None
        task.error = structured

        if self._logger:
            self._logger.error(
                component="DownloadQueueManager",
                message=structured.message_en,
                error_code=structured.code,
                task_id=task_id,
                stage=current_stage,
            )

        self._record_history_entry(task)
        self._events.emit_task_status_changed(task)
