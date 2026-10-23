"""Unit and integration tests for Phase 4 App Shell, Portable Path Resolution, and BridgeAPI additions."""

from pathlib import Path
from threading import Event
from typing import Optional
import pytest

pytestmark = pytest.mark.integration

from pladaz.bridge.api import BridgeAPI
from pladaz.bridge.events import EventDispatcher
from pladaz.domain.enums import AudioProcessMode, TaskStatus
from pladaz.domain.errors import ErrorCode
from pladaz.domain.models import (
    AudioFormat,
    HistoryEntry,
    RawSourceEntry,
    RawTrackInfo,
    SDCardStatus,
    StreamPlan,
    TrackMetadata,
    TrackTask,
    ValidationResult,
)
from pladaz.main import create_app_context
from pladaz.paths import resolve_app_paths
from pladaz.services.config_store import ConfigHistoryStore
from pladaz.services.folder_organizer import SmartFolderOrganizer
from pladaz.services.logger import PladazLogger
from pladaz.services.queue_manager import DownloadQueueManager
from pladaz.services.sd_card_manager import SDCardManager
from pladaz.services.source_adapter import DownloadSourceAdapter


class FakeDriveProbe:
    def __init__(self, root: Path) -> None:
        self.root = root

    def list_removable_drives(self) -> list[SDCardStatus]:
        return [
            SDCardStatus(
                drive_root=str(self.root),
                destination_dir=str(self.root),
                is_connected=True,
                is_writable=True,
                free_bytes=16 * 1024 * 1024 * 1024,
                total_bytes=32 * 1024 * 1024 * 1024,
                volume_label="ECHO_SD",
            )
        ]

    def probe_destination(self, dest: Path) -> SDCardStatus:
        return SDCardStatus(
            drive_root=str(self.root),
            destination_dir=str(dest),
            is_connected=True,
            is_writable=True,
            free_bytes=16 * 1024 * 1024 * 1024,
            total_bytes=32 * 1024 * 1024 * 1024,
            volume_label="ECHO_SD",
        )

    def copy_file_with_fsync(self, src: Path, dst: Path) -> None:
        dst.write_bytes(src.read_bytes())


def test_resolve_app_paths_dev_vs_frozen(tmp_path: Path) -> None:
    """Verify portable path resolution in dev mode vs PyInstaller frozen (--onedir) mode (DEC-023, DEC-038)."""
    # 1. Dev mode
    dev_root = tmp_path / "dev_repo"
    (dev_root / "ui").mkdir(parents=True)
    (dev_root / "ui" / "index.html").write_text("<html></html>", encoding="utf-8")
    (dev_root / "bin").mkdir(parents=True)
    (dev_root / "bin" / "ffmpeg.exe").write_bytes(b"FFMPEG")

    dev_paths = resolve_app_paths(frozen=False, dev_root=dev_root)
    assert dev_paths.app_root == dev_root.resolve()
    assert dev_paths.bundle_root == dev_root.resolve()
    assert dev_paths.ui_entry == (dev_root / "ui" / "index.html").resolve()
    assert dev_paths.config_file == (dev_root / "config.json").resolve()
    assert dev_paths.ytdlp_path == (dev_root / "yt-dlp.exe").resolve()
    assert dev_paths.ffmpeg_path == (dev_root / "bin" / "ffmpeg.exe").resolve()

    # 2. Frozen PyInstaller --onedir mode (PLADAZ.exe in dist/PLADAZ, _internal as _MEIPASS)
    dist_dir = tmp_path / "dist" / "PLADAZ"
    internal_dir = dist_dir / "_internal"
    (internal_dir / "ui").mkdir(parents=True)
    (internal_dir / "ui" / "index.html").write_text("<html>frozen</html>", encoding="utf-8")
    (internal_dir / "bin").mkdir(parents=True)
    (internal_dir / "bin" / "ffmpeg.exe").write_bytes(b"FFMPEG_BUNDLED")
    exe_file = dist_dir / "PLADAZ.exe"
    exe_file.write_bytes(b"EXE")

    frozen_paths = resolve_app_paths(
        frozen=True,
        executable_path=exe_file,
        meipass_path=internal_dir,
    )
    assert frozen_paths.app_root == dist_dir.resolve()
    assert frozen_paths.bundle_root == internal_dir.resolve()
    # Mutable portable files and external yt-dlp.exe MUST be in app_root next to PLADAZ.exe
    assert frozen_paths.config_file == (dist_dir / "config.json").resolve()
    assert frozen_paths.history_file == (dist_dir / "history.json").resolve()
    assert frozen_paths.logs_dir == (dist_dir / "logs").resolve()
    assert frozen_paths.temp_dir == (dist_dir / "temp").resolve()
    assert frozen_paths.ytdlp_path == (dist_dir / "yt-dlp.exe").resolve()
    # Bundled read-only assets come from _internal (_MEIPASS)
    assert frozen_paths.ui_entry == (internal_dir / "ui" / "index.html").resolve()
    assert frozen_paths.ffmpeg_path == (internal_dir / "bin" / "ffmpeg.exe").resolve()


def test_app_shell_startup_cleans_temp_and_recovers_corrupt_config(tmp_path: Path) -> None:
    """Verify create_app_context() cleans temp/, recovers corrupt config.json, and exposes startup_error."""
    app_root = tmp_path / "app"
    (app_root / "ui").mkdir(parents=True)
    (app_root / "ui" / "index.html").write_text("<html></html>", encoding="utf-8")
    stale_temp = app_root / "temp" / "task-stale"
    stale_temp.mkdir(parents=True)
    (stale_temp / "leftover.m4a").write_bytes(b"stale")

    # Write a corrupted config.json
    (app_root / "config.json").write_text("{broken json", encoding="utf-8")

    paths = resolve_app_paths(frozen=False, dev_root=app_root)
    ctx = create_app_context(paths)
    try:
        assert not stale_temp.exists()
        state = ctx.bridge.get_initial_state()
        assert state["success"] is True
        assert state["disclaimer_accepted"] is False
        assert state["startup_error"] is not None
        assert state["startup_error"]["code"] == ErrorCode.ERR_CONFIG_CORRUPT
        assert state["ytdlp_status"]["present"] is False
    finally:
        ctx.shutdown()


def test_bridge_phase4_methods(tmp_path: Path) -> None:
    """Verify scan_storage_devices, browse_destination_folder, get_cover_preview, clear_history, locate_ytdlp_file, get_recent_logs, open_folder, and quit_app."""
    app_root = tmp_path / "portable"
    sd_root = tmp_path / "sdcard"
    sd_root.mkdir(parents=True)

    logger = PladazLogger(log_dir=app_root / "logs")
    logger.info("TestComponent", "Normal startup log line")
    logger.info("TestComponent", "Secret cookie SID=SUPERSECRETCOOKIE12345 in log")

    config_store = ConfigHistoryStore(base_dir=app_root, logger=logger)
    events = EventDispatcher()
    sd_manager = SDCardManager(drive_probe=FakeDriveProbe(sd_root), logger=logger)
    source_adapter = DownloadSourceAdapter(ytdlp_path=app_root / "yt-dlp.exe", logger=logger)
    # Monkeypatch get_version to simulate valid binary when file exists
    source_adapter.get_version = lambda p=None: "2026.10.01" if Path(p or source_adapter.ytdlp_path).exists() else None  # type: ignore[method-assign]

    from pladaz.services.audio_processor import AudioProcessingService
    from pladaz.services.metadata_service import MetadataAlbumArtService
    from pladaz.services.output_validator import OutputValidator

    qm = DownloadQueueManager(
        source_adapter=source_adapter,
        metadata_service=MetadataAlbumArtService(logger=logger),
        folder_organizer=SmartFolderOrganizer(),
        audio_processor=AudioProcessingService(logger=logger),
        output_validator=OutputValidator(),
        sd_card_manager=sd_manager,
        config_store=config_store,
        event_dispatcher=events,
        temp_root=app_root / "temp",
        logger=logger,
    )

    opened_folders: list[Path] = []
    quit_called = False

    def _on_quit() -> None:
        nonlocal quit_called
        quit_called = True

    external_ytdlp = tmp_path / "Downloads" / "yt-dlp.exe"
    external_ytdlp.parent.mkdir(parents=True)
    external_ytdlp.write_bytes(b"MZ_FAKE_YTDLP")

    cookies_file = tmp_path / "Downloads" / "cookies.txt"
    cookies_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")

    bridge = BridgeAPI(
        queue_manager=qm,
        source_adapter=source_adapter,
        sd_card_manager=sd_manager,
        config_store=config_store,
        file_dialog_fn=lambda: str(cookies_file),
        folder_dialog_fn=lambda: str(sd_root / "Music"),
        exe_dialog_fn=lambda: str(external_ytdlp),
        open_folder_fn=lambda p: opened_folders.append(p),
        quit_fn=_on_quit,
        log_file_path=logger.log_file_path,
    )

    # 1. scan_storage_devices & select_detected_drive (strictly validated against backend removable drives)
    scan_res = bridge.scan_storage_devices()
    assert scan_res["success"] is True
    assert len(scan_res["devices"]) == 1
    assert scan_res["devices"][0]["volume_label"] == "ECHO_SD"

    bad_drive_res = bridge.select_detected_drive("Z:\\NotInDetectedList")
    assert bad_drive_res["success"] is False
    assert bad_drive_res["error"]["code"] == ErrorCode.ERR_SDCARD_DISCONNECTED

    good_drive_res = bridge.select_detected_drive(str(sd_root))
    assert good_drive_res["success"] is True
    assert good_drive_res["selected_path"] == str(sd_root)

    # 2. browse_destination_folder (0 args from UI, uses native dialog callback)
    (sd_root / "Music").mkdir(parents=True)
    browse_res = bridge.browse_destination_folder()
    assert browse_res["success"] is True
    assert browse_res["selected_path"] == str(sd_root / "Music")
    assert config_store.load_config()["destination_path"] == str(sd_root / "Music")

    # 2b. select_cookies_file (0 args) and explicit clear_cookies_file (no magic "")
    cookies_res = bridge.select_cookies_file()
    assert cookies_res["success"] is True
    assert cookies_res["filename"] == "cookies.txt"
    assert config_store.load_config()["cookies_file_path"] == str(cookies_file)

    clear_cookies_res = bridge.clear_cookies_file()
    assert clear_cookies_res["success"] is True
    assert clear_cookies_res["selected_path"] is None
    assert config_store.load_config()["cookies_file_path"] is None

    # 3. get_cover_preview (Base64 JPEG Data URL without sending raw bytes in TaskDTO)
    fake_jpeg = b"\xff\xd8\xff\xe0FAKE_JPEG_BYTES\xff\xd9"
    task = TrackTask(
        task_id="task-cover1",
        entry_url="https://music.youtube.com/watch?v=abc",
        batch_id="batch-1",
        status=TaskStatus.COMPLETED,
        metadata=TrackMetadata(title="Neon Track", cover_jpeg=fake_jpeg),
    )
    qm._tasks.append(task)
    cover_res = bridge.get_cover_preview("task-cover1")
    assert cover_res["success"] is True
    assert cover_res["data_url"].startswith("data:image/jpeg;base64,")

    # 4. clear_history (Board 07)
    config_store.append_history(
        HistoryEntry(
            task_id="task-h1",
            finished_at="2026-10-23T12:00:00Z",
            status=TaskStatus.COMPLETED,
            title="Song 1",
            album_artist="Artist 1",
            album="Album 1",
            target_file_path="E:\\Music\\01 - Song 1.m4a",
            source_url="https://music.youtube.com/watch?v=1",
        )
    )
    assert len(bridge.get_history()["entries"]) == 1
    clear_res = bridge.clear_history()
    assert clear_res["success"] is True
    assert len(bridge.get_history()["entries"]) == 0

    # 5. locate_ytdlp_file (Board 09 - 0 args from UI, uses native exe_dialog_fn)
    locate_res = bridge.locate_ytdlp_file()
    assert locate_res["success"] is True
    assert locate_res["present"] is True
    assert locate_res["version"] == "2026.10.01"
    assert (app_root / "yt-dlp.exe").exists()

    # 6. get_recent_logs (Board 17) - verify redaction
    logs_res = bridge.get_recent_logs(max_lines=20)
    assert logs_res["success"] is True
    joined_logs = "\n".join(logs_res["lines"])
    assert "Normal startup log line" in joined_logs
    assert "SUPERSECRETCOOKIE12345" not in joined_logs

    # 7. open_folder & quit_app
    open_dest = bridge.open_folder("destination")
    assert open_dest["success"] is True
    assert opened_folders[-1] == sd_root / "Music"

    open_logs = bridge.open_folder("logs")
    assert open_logs["success"] is True
    assert opened_folders[-1] == app_root / "logs"

    bridge.quit_app()
    assert quit_called is True
    logger.close()


def test_cancel_active_task_halts_queue_waiting_for_resume(tmp_path: Path) -> None:
    """Verify Board 11 decision: cancelling an active Downloading task marks it Failed (ERR_TASK_CANCELLED)
    and halts the queue so remaining Queued tasks stay Queued until resume_queue() is called."""
    app_root = tmp_path / "app"
    sd_root = tmp_path / "sd"
    sd_root.mkdir(parents=True)

    config_store = ConfigHistoryStore(base_dir=app_root)
    config_store.save_config({"destination_path": str(sd_root), "disclaimer_accepted": True})
    events = EventDispatcher()
    sd_manager = SDCardManager(drive_probe=FakeDriveProbe(sd_root))

    started_first_download = Event()

    class BlockingAdapter:
        def extract_entries(self, url: str, cookies_path: Optional[Path] = None) -> list[RawSourceEntry]:
            return [
                RawSourceEntry(entry_url="https://www.youtube.com/watch?v=track1", title_hint="T1", batch_id="b1", index_in_batch=0),
                RawSourceEntry(entry_url="https://www.youtube.com/watch?v=track2", title_hint="T2", batch_id="b1", index_in_batch=1),
            ]

        def fetch_track_info(self, entry_url: str, cookies_path: Optional[Path] = None) -> RawTrackInfo:
            return RawTrackInfo(
                entry_url=entry_url,
                title="Track",
                artist="Artist",
                album="Album",
                album_artist="Artist",
                track_number=1,
                disc_number=1,
                release_year="2026",
                genre="Pop",
                thumbnail_url=None,
                audio_formats=[AudioFormat(format_id="140", acodec="mp4a.40.2", abr=128.0, ext="m4a")],
            )

        def plan_stream(self, info: RawTrackInfo) -> StreamPlan:
            return StreamPlan(format_id="140", mode=AudioProcessMode.REMUX_AAC)

        def download_stream(
            self,
            entry_url: str,
            plan: StreamPlan,
            temp_dir: Path,
            progress_cb: Optional[object] = None,
            cancel_event: Optional[Event] = None,
            cookies_path: Optional[Path] = None,
        ) -> Path:
            started_first_download.set()
            assert cancel_event is not None
            cancel_event.wait(timeout=5.0)
            from pladaz.domain.errors import TaskCancelledError
            raise TaskCancelledError()

    from pladaz.services.audio_processor import AudioProcessingService
    from pladaz.services.metadata_service import MetadataAlbumArtService
    from pladaz.services.output_validator import OutputValidator

    qm = DownloadQueueManager(
        source_adapter=BlockingAdapter(),  # type: ignore[arg-type]
        metadata_service=MetadataAlbumArtService(),
        folder_organizer=SmartFolderOrganizer(),
        audio_processor=AudioProcessingService(),
        output_validator=OutputValidator(),
        sd_card_manager=sd_manager,
        config_store=config_store,
        event_dispatcher=events,
        temp_root=app_root / "temp",
    )

    added = qm.enqueue_url("https://www.youtube.com/playlist?list=PL123")
    assert len(added) == 2
    t1_id, t2_id = added[0].task_id, added[1].task_id

    qm.start_queue(background=True)
    assert started_first_download.wait(timeout=5.0)

    # Cancel active task 1
    assert qm.cancel_task(t1_id) is True
    assert qm.wait_for_idle(timeout=5.0) is True

    t1 = qm.get_task(t1_id)
    t2 = qm.get_task(t2_id)
    assert t1 is not None and t1.status == TaskStatus.FAILED
    assert t1.error is not None and t1.error.code == ErrorCode.ERR_TASK_CANCELLED
    # Task 2 MUST remain Queued and the queue MUST be halted waiting for Resume
    assert t2 is not None and t2.status == TaskStatus.QUEUED
    assert qm.is_queue_halted() is True


def test_ui_bundle_offline_no_cdn_and_constraints() -> None:
    """Verify ui/ assets exist, contain zero external CDN URLs (DEC-029), include TBA-023 placeholder, and exclude Board 12 Picker."""
    repo_root = Path(__file__).resolve().parents[1]
    index_html = (repo_root / "ui" / "index.html").read_text(encoding="utf-8")
    built_css = (repo_root / "ui" / "app.built.css").read_text(encoding="utf-8")
    bridge_js = (repo_root / "ui" / "js" / "bridge.js").read_text(encoding="utf-8")
    app_js = (repo_root / "ui" / "js" / "app.js").read_text(encoding="utf-8")

    # 1. Zero external CDN dependencies (DEC-029)
    for forbidden_cdn in (
        "cdn.tailwindcss.com",
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "unpkg.com",
        "jsdelivr.net",
    ):
        assert forbidden_cdn not in index_html
        assert forbidden_cdn not in built_css

    # 2. TBA-023 exact placeholder in Board 04 Disclaimer modal
    assert "[DISCLAIMER TEXT — wording to be supplied by the project owner]" in index_html

    # 3. Board 12 (Choose Tracks Picker) excluded per user decision
    assert "modal-picker" not in index_html
    assert "Choose Tracks" not in index_html

    # 4. All 6 Bridge events registered in bridge.js and subscribed in app.js
    for evt in (
        "queue:updated",
        "task:progress",
        "task:status_changed",
        "task:conflict_prompt",
        "sdcard:status_changed",
        "system:error",
    ):
        assert evt in bridge_js
        assert evt in app_js

    # 5. Design Direction minimum font size (>= 12px): zero text-[9px], text-[10px], or text-[11px]
    for sub12 in ("text-[9px]", "text-[10px]", "text-[11px]", "font-size: 11px", "font-size:11px"):
        assert sub12 not in index_html
        assert sub12 not in app_js
        assert sub12 not in built_css

    # 6. Segmented progress bar (no smooth gradient bar), speech-bubble tail, and dark navy Failed badge
    assert "bg-gradient-to-r" not in index_html
    assert "bg-gradient-to-r" not in app_js
    assert "speech-bubble" in index_html
    assert ".speech-bubble:before" in built_css or ".speech-bubble::before" in built_css
    assert "✕ Failed" in app_js


def test_ui_css_hidden_utility_not_overridden_by_components() -> None:
    """Regression test: Ensure .hidden utility is never overridden by .modal-backdrop, .btn, .pbtn, or .ibtn in app.built.css."""
    repo_root = Path(__file__).resolve().parents[1]
    built_css = (repo_root / "ui" / "app.built.css").read_text(encoding="utf-8")

    # .hidden must enforce display:none!important and appear after custom display classes
    assert "display:none!important" in built_css
    last_hidden_pos = built_css.rfind(".hidden")
    for selector in (".modal-backdrop{", ".btn{", ".pbtn{", ".ibtn{", ".main-workspace-grid{"):
        comp_pos = built_css.find(selector)
        assert comp_pos != -1, f"Missing expected component selector {selector} in app.built.css"
        assert last_hidden_pos > comp_pos, (
            f".hidden (pos {last_hidden_pos}) must appear after {selector} (pos {comp_pos}) "
            "so hidden modals and buttons are never forced visible"
        )


