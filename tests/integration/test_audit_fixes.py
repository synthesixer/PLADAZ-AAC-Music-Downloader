"""Regression tests for defects found in the 2026-10-24 final audit (F-03..F-16, P-05, P-18, P-19)."""

from pathlib import Path
import shutil
import subprocess
import sys
from threading import Event, Thread, Timer
import time
from typing import Any, Optional
import pytest

pytestmark = pytest.mark.integration

from pladaz.bridge.api import BridgeAPI
from pladaz.bridge.dto import history_entry_to_dto
from pladaz.bridge.events import EventDispatcher
from pladaz.domain.enums import (
    AudioProcessMode,
    ConflictAction,
    ConflictScope,
    TaskStatus,
)
from pladaz.domain.errors import (
    ErrorCode,
    SourceNetworkTimeoutError,
    TaskCancelledError,
)
from pladaz.domain.models import (
    AudioFormat,
    HistoryEntry,
    RawSourceEntry,
    RawTrackInfo,
    SDCardStatus,
    StreamPlan,
    TrackMetadata,
    TrackTask,
)
from pladaz.services.audio_processor import AudioProcessingService
from pladaz.services.config_store import ConfigHistoryStore
from pladaz.services.folder_organizer import SmartFolderOrganizer
from pladaz.services.metadata_matcher import HttpExternalMetadataFetcher
from pladaz.services.metadata_service import MetadataAlbumArtService
from pladaz.services.output_validator import OutputValidator
from pladaz.services.queue_manager import DownloadQueueManager
from pladaz.services.sd_card_manager import OVERWRITE_TEMP_SUFFIX, SDCardManager
from pladaz.services.source_adapter import DownloadSourceAdapter, parse_track_info


class FakeDriveProbe:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.copy_destinations: list[Path] = []

    def list_removable_drives(self) -> list[SDCardStatus]:
        return [self.probe_destination(self.root)]

    def probe_destination(self, dest: Path) -> SDCardStatus:
        return SDCardStatus(
            drive_root=str(self.root),
            destination_dir=str(dest),
            is_connected=True,
            is_writable=True,
            free_bytes=16 * 1024**3,
            total_bytes=32 * 1024**3,
            volume_label="ECHO_SD",
        )

    def copy_file_with_fsync(self, src: Path, dst: Path) -> None:
        self.copy_destinations.append(Path(dst))
        shutil.copyfile(src, dst)


def _track_info(url: str) -> RawTrackInfo:
    return RawTrackInfo(
        entry_url=url,
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


class BlockingAdapter:
    """Two-entry playlist whose first download blocks until cancelled."""

    def __init__(self) -> None:
        self.started = Event()

    def extract_entries(self, url: str, cookies_path: Optional[Path] = None) -> list[RawSourceEntry]:
        return [
            RawSourceEntry(entry_url=f"https://www.youtube.com/watch?v=t{i}", title_hint=None, batch_id="b", index_in_batch=i)
            for i in range(3)
        ]

    def fetch_track_info(self, entry_url: str, cookies_path: Optional[Path] = None) -> RawTrackInfo:
        return _track_info(entry_url)

    def plan_stream(self, info: RawTrackInfo) -> StreamPlan:
        return StreamPlan(format_id="140", mode=AudioProcessMode.REMUX_AAC)

    def download_stream(self, entry_url: str, plan: StreamPlan, temp_dir: Path, progress_cb: Any = None,
                        cancel_event: Optional[Event] = None, cookies_path: Optional[Path] = None) -> Path:
        self.started.set()
        assert cancel_event is not None
        cancel_event.wait(timeout=5.0)
        time.sleep(0.3)  # simulate a worker that needs a moment to unwind
        raise TaskCancelledError()


def _make_queue(tmp_path: Path, adapter: Any, config_store: Optional[ConfigHistoryStore] = None,
                events: Optional[EventDispatcher] = None) -> tuple[DownloadQueueManager, ConfigHistoryStore, Path]:
    sd_root = tmp_path / "sd"
    sd_root.mkdir(parents=True, exist_ok=True)
    store = config_store or ConfigHistoryStore(base_dir=tmp_path / "app")
    store.save_config({"destination_path": str(sd_root), "disclaimer_accepted": True})
    qm = DownloadQueueManager(
        source_adapter=adapter,
        metadata_service=MetadataAlbumArtService(),
        folder_organizer=SmartFolderOrganizer(),
        audio_processor=AudioProcessingService(),
        output_validator=OutputValidator(),
        sd_card_manager=SDCardManager(drive_probe=FakeDriveProbe(sd_root)),
        config_store=store,
        event_dispatcher=events or EventDispatcher(),
        temp_root=tmp_path / "temp",
        sd_poll_interval_sec=0.2,
    )
    return qm, store, sd_root


# --- F-03 / F-04: shutdown waits for the worker and discards queued tasks without history ---

def test_f03_f04_shutdown_joins_worker_and_discards_queued_without_history(tmp_path: Path) -> None:
    adapter = BlockingAdapter()
    qm, store, _ = _make_queue(tmp_path, adapter)
    added = qm.enqueue_url("https://www.youtube.com/playlist?list=PL1")
    qm.start_queue(background=True)
    assert adapter.started.wait(timeout=5.0)

    qm.shutdown(timeout=5.0)

    assert qm._worker_thread is not None and not qm._worker_thread.is_alive()
    remaining = {t.task_id for t in qm.get_tasks()}
    assert added[1].task_id not in remaining and added[2].task_id not in remaining
    history = store.load_history()
    # Only the task that was actually running is recorded; queued tasks are discarded silently.
    assert [e.task_id for e in history] == [added[0].task_id]
    assert history[0].error_code == ErrorCode.ERR_TASK_CANCELLED


# --- F-03: every copy is staged under .pladaz-tmp, never written directly to the final name ---

def test_f03_copy_without_overwrite_is_staged(tmp_path: Path, sample_m4a_path: Path) -> None:
    sd_root = tmp_path / "sd"
    sd_root.mkdir()
    probe = FakeDriveProbe(sd_root)
    manager = SDCardManager(drive_probe=probe)
    target = sd_root / "A" / "B" / "Song.m4a"

    final = manager.copy_and_verify(sample_m4a_path, target, overwrite=False)

    assert final == target and target.exists()
    assert probe.copy_destinations == [target.with_name(target.name + OVERWRITE_TEMP_SUFFIX)]
    assert not target.with_name(target.name + OVERWRITE_TEMP_SUFFIX).exists()


# --- P-05: cancel and timeout work while yt-dlp prints nothing ---

@pytest.fixture
def silent_ytdlp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Replace the yt-dlp process with one that sleeps without printing anything."""
    fake = tmp_path / "yt-dlp.exe"
    fake.write_bytes(b"")
    real_popen = subprocess.Popen

    def fake_popen(cmd: list[str], *args: Any, **kwargs: Any) -> subprocess.Popen:
        return real_popen([sys.executable, "-c", "import time; time.sleep(30)"], *args, **kwargs)

    monkeypatch.setattr("pladaz.services.source_adapter.subprocess.Popen", fake_popen)
    return fake


def test_p05_cancel_while_ytdlp_is_silent(tmp_path: Path, silent_ytdlp: Path) -> None:
    adapter = DownloadSourceAdapter(ytdlp_path=silent_ytdlp)
    cancel_ev = Event()
    Timer(0.5, cancel_ev.set).start()
    start = time.monotonic()
    with pytest.raises(TaskCancelledError):
        adapter.download_stream(
            entry_url="https://www.youtube.com/watch?v=abc",
            plan=StreamPlan(format_id="140", mode=AudioProcessMode.REMUX_AAC),
            temp_dir=tmp_path / "dl",
            cancel_event=cancel_ev,
        )
    assert time.monotonic() - start < 5.0


def test_p05_timeout_while_ytdlp_is_silent(tmp_path: Path, silent_ytdlp: Path) -> None:
    adapter = DownloadSourceAdapter(ytdlp_path=silent_ytdlp, download_timeout_sec=0.5)
    start = time.monotonic()
    with pytest.raises(SourceNetworkTimeoutError):
        adapter.download_stream(
            entry_url="https://www.youtube.com/watch?v=abc",
            plan=StreamPlan(format_id="140", mode=AudioProcessMode.REMUX_AAC),
            temp_dir=tmp_path / "dl",
        )
    assert time.monotonic() - start < 5.0


# --- P-18: concurrent history appends never lose entries ---

def test_p18_concurrent_history_appends_keep_all_entries(tmp_path: Path) -> None:
    store = ConfigHistoryStore(base_dir=tmp_path)
    errors: list[BaseException] = []

    def worker(prefix: str) -> None:
        for i in range(15):
            try:
                store.append_history(HistoryEntry(
                    task_id=f"{prefix}-{i}", finished_at="2026-10-24T00:00:00", status=TaskStatus.FAILED,
                    title=None, album_artist=None, album=None, target_file_path=None,
                    source_url="https://www.youtube.com/watch?v=x",
                ))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

    threads = [Thread(target=worker, args=(p,)) for p in ("a", "b", "c")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(store.load_history()) == 45


# --- P-19: fallback encode prefers audio-only streams over muxed video ---

def test_p19_plan_stream_prefers_audio_only_over_muxed_video() -> None:
    info = parse_track_info(
        {
            "title": "Song",
            "formats": [
                {"format_id": "18", "acodec": "mp4a.40.2", "vcodec": "avc1.42001E", "ext": "mp4", "tbr": 500.0},
                {"format_id": "251", "acodec": "opus", "vcodec": "none", "ext": "webm", "abr": 130.0},
            ],
        },
        entry_url="https://www.youtube.com/watch?v=abc",
    )
    plan = DownloadSourceAdapter(ytdlp_path=Path("yt-dlp.exe")).plan_stream(info)
    assert plan.format_id == "251"
    assert plan.mode == AudioProcessMode.ENCODE_AAC_LC


# --- F-09: MusicBrainz User-Agent follows the saved setting without a restart ---

def test_f09_musicbrainz_user_agent_is_read_live() -> None:
    current = {"ua": ""}
    seen_headers: list[dict[str, str]] = []

    def fake_get_json(url: str, headers: dict[str, str], timeout: float) -> dict[str, Any]:
        seen_headers.append(headers)
        return {"results": [], "recordings": []}

    fetcher = HttpExternalMetadataFetcher(
        musicbrainz_user_agent_provider=lambda: current["ua"],
        http_get_json=fake_get_json,
        sleep_fn=lambda _s: None,
    )
    assert fetcher.query_musicbrainz("Song", "Artist") == []
    assert seen_headers == []

    current["ua"] = "MyApp/1.0 (me@example.com)"
    fetcher.query_musicbrainz("Song", "Artist")
    assert seen_headers[-1]["User-Agent"] == "MyApp/1.0 (me@example.com)"


# --- F-10: history keeps has_cover so the UI can show the No cover chip ---

def test_f10_history_records_has_cover(tmp_path: Path) -> None:
    qm, store, _ = _make_queue(tmp_path, BlockingAdapter())
    task = TrackTask(task_id="task-nocover", entry_url="https://www.youtube.com/watch?v=x", batch_id="b",
                     status=TaskStatus.COMPLETED, stage=None, progress_percent=100.0)
    task.metadata = TrackMetadata(title="T", track_artist=None, album=None, album_artist=None,
                                  track_number=None, total_tracks=None, disc_number=None, total_discs=None,
                                  year=None, genre=None, cover_jpeg=None)
    qm._record_history_entry(task)

    entries = store.load_history()
    assert entries[-1].has_cover is False
    assert history_entry_to_dto(entries[-1])["has_cover"] is False


# --- F-16: failures to write history surface as system:error ---

def test_f16_history_write_failure_emits_system_error(tmp_path: Path) -> None:
    class BrokenStore(ConfigHistoryStore):
        def append_history(self, entry: HistoryEntry) -> None:
            raise OSError("disk full")

    events = EventDispatcher()
    received: list[tuple[str, dict[str, Any]]] = []
    events.subscribe(lambda et, data: received.append((et, data)))
    qm, _, _ = _make_queue(tmp_path, BlockingAdapter(), config_store=BrokenStore(base_dir=tmp_path / "app"), events=events)
    task = TrackTask(task_id="task-x", entry_url="https://www.youtube.com/watch?v=x", batch_id="b",
                     status=TaskStatus.FAILED, stage=None, progress_percent=0.0)
    qm._record_history_entry(task)

    sys_errors = [d for et, d in received if et == EventDispatcher.EVENT_SYSTEM_ERROR]
    assert len(sys_errors) == 1
    assert sys_errors[0]["error"]["code"] == ErrorCode.ERR_HISTORY_WRITE_FAILED


# --- F-14: resolve_conflict only answers an active prompt ---

def test_f14_resolve_conflict_without_prompt_is_rejected(tmp_path: Path) -> None:
    qm, _, _ = _make_queue(tmp_path, BlockingAdapter())
    added = qm.enqueue_url("https://www.youtube.com/playlist?list=PL1")
    assert qm.resolve_conflict(added[0].task_id, ConflictAction.OVERWRITE, ConflictScope.QUEUE) is False
    assert qm._queue_conflict_rule is None


# --- F-12 / F-13: bridge error codes are declared, and update_config only accepts known keys ---

def _bridge(tmp_path: Path) -> tuple[BridgeAPI, ConfigHistoryStore]:
    qm, store, _ = _make_queue(tmp_path, BlockingAdapter())
    bridge = BridgeAPI(
        queue_manager=qm,
        source_adapter=DownloadSourceAdapter(ytdlp_path=tmp_path / "yt-dlp.exe"),
        sd_card_manager=qm._sd_card_manager,
        config_store=store,
    )
    return bridge, store


def test_f12_bridge_error_codes_are_declared(tmp_path: Path) -> None:
    bridge, _ = _bridge(tmp_path)
    assert bridge.retry_task("missing")["error"]["code"] == ErrorCode.ERR_TASK_RETRY_FAILED
    assert bridge.remove_task("missing")["error"]["code"] == ErrorCode.ERR_TASK_REMOVE_FAILED
    assert bridge.resolve_conflict("missing", "skip")["error"]["code"] == ErrorCode.ERR_CONFLICT_NOT_FOUND


def test_f13_update_config_rejects_unknown_keys_and_bad_types(tmp_path: Path) -> None:
    bridge, store = _bridge(tmp_path)
    before = store.load_config()

    for bad in ({"cookies_file_path": "C:/evil.txt"}, {"disclaimer_accepted": True}, {"require_album_art": "yes"},
                {"musicbrainz_user_agent": 42}):
        res = bridge.update_config(bad)
        assert res["success"] is False, bad
        assert res["error"]["code"] == ErrorCode.ERR_CONFIG_INVALID

    assert store.load_config() == before
    ok = bridge.update_config({"require_album_art": True, "musicbrainz_user_agent": "A/1.0"})
    assert ok["success"] is True
    assert store.load_config()["require_album_art"] is True


# --- F-11: verify_sd_card cross-checks history.json entries ---

def test_f11_verify_sd_card_reads_history_entries(tmp_path: Path, sample_m4a_path: Path) -> None:
    sd_root = tmp_path / "sd"
    (sd_root / "A" / "B").mkdir(parents=True)
    shutil.copyfile(sample_m4a_path, sd_root / "A" / "B" / "Song.m4a")
    store = ConfigHistoryStore(base_dir=tmp_path / "app")
    store.append_history(HistoryEntry(
        task_id="t1", finished_at="2026-10-24T00:00:00", status=TaskStatus.COMPLETED, title="Song",
        album_artist="A", album="B", target_file_path=str(sd_root / "A" / "B" / "Song.m4a"),
        source_url="https://www.youtube.com/watch?v=x",
    ))
    script = Path(__file__).resolve().parents[2] / "scripts" / "verify_sd_card.py"
    proc = subprocess.run(
        [sys.executable, str(script), str(sd_root), "--history", str(store.history_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    assert "Could not parse history.json" not in proc.stdout
    assert "Completed entries in history: 1" in proc.stdout
