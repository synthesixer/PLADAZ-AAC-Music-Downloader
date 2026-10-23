"""Integration tests for DownloadQueueManager, Sequential Worker, Cancel, SD Card Watcher, and BridgeAPI (TC-016, TC-018, TC-019)."""

from pathlib import Path
import shutil
from threading import Event
import time
from typing import Any, Optional

from pladaz.bridge.api import BridgeAPI
from pladaz.bridge.events import EventDispatcher
from pladaz.domain.enums import AudioProcessMode, TaskStatus
from pladaz.domain.errors import ErrorCode, TaskCancelledError
from pladaz.domain.models import (
    AudioFormat,
    RawSourceEntry,
    RawTrackInfo,
    StreamPlan,
)
from pladaz.services.audio_processor import AudioProcessingService
from pladaz.services.config_store import (
    CONFIG_KEY_REQUIRE_ALBUM_ART,
    ConfigHistoryStore,
)
from pladaz.services.folder_organizer import SmartFolderOrganizer
from pladaz.services.metadata_service import MetadataAlbumArtService
from pladaz.services.output_validator import OutputValidator
from pladaz.services.queue_manager import DownloadQueueManager
from pladaz.services.sd_card_manager import SDCardManager
from tests.integration.test_sd_card_manager import FakeDriveProbe


class ControllableSourceAdapter:
    """Fake DownloadSourceAdapter allowing slow/blocking downloads to test mid-download Cancel (TC-016) and SD disconnect (TC-019)."""

    def __init__(
        self,
        sample_m4a: Path,
        tracks_by_url: dict[str, RawTrackInfo],
        block_download_event: Optional[Event] = None,
        download_started_event: Optional[Event] = None,
    ) -> None:
        self.sample_m4a = sample_m4a
        self.tracks_by_url = tracks_by_url
        self.block_download_event = block_download_event
        self.download_started_event = download_started_event

    def extract_entries(
        self,
        url: str,
        cookies_path: Optional[Path] = None,
    ) -> list[RawSourceEntry]:
        if url in self.tracks_by_url:
            info = self.tracks_by_url[url]
            return [
                RawSourceEntry(
                    entry_url=url,
                    title_hint=info.title,
                    batch_id="batch-1",
                    index_in_batch=0,
                )
            ]
        return [
            RawSourceEntry(
                entry_url=u,
                title_hint=t.title,
                batch_id="batch-pl",
                index_in_batch=idx,
            )
            for idx, (u, t) in enumerate(self.tracks_by_url.items())
        ]

    def fetch_track_info(
        self,
        entry_url: str,
        cookies_path: Optional[Path] = None,
    ) -> RawTrackInfo:
        return self.tracks_by_url[entry_url]

    def plan_stream(self, info: RawTrackInfo) -> StreamPlan:
        return StreamPlan(format_id="140", mode=AudioProcessMode.REMUX_AAC)

    def download_stream(
        self,
        entry_url: str,
        plan: StreamPlan,
        temp_dir: Path,
        progress_cb: Any = None,
        cancel_event: Optional[Event] = None,
        cookies_path: Optional[Path] = None,
    ) -> Path:
        dst = temp_dir / "raw_stream.m4a"
        shutil.copyfile(self.sample_m4a, dst)
        if progress_cb:
            progress_cb(25.0, "1.2MiB/s", "00:02")
        if self.download_started_event is not None:
            self.download_started_event.set()

        if self.block_download_event is not None:
            while not self.block_download_event.is_set():
                if cancel_event is not None and cancel_event.is_set():
                    raise TaskCancelledError()
                time.sleep(0.02)

        if cancel_event is not None and cancel_event.is_set():
            raise TaskCancelledError()
        return dst


class FastPassAudioProcessor(AudioProcessingService):
    def to_m4a(
        self,
        input_path: Path,
        output_path: Path,
        mode: AudioProcessMode,
        cancel_event: Optional[Event] = None,
    ) -> Path:
        if cancel_event is not None and cancel_event.is_set():
            raise TaskCancelledError()
        shutil.copyfile(input_path, output_path)
        return output_path


def _track(url: str, title: str) -> RawTrackInfo:
    return RawTrackInfo(
        entry_url=url,
        title=title,
        artist="QueueArtist",
        album="QueueAlbum",
        album_artist="QueueArtist",
        track_number=1,
        disc_number=1,
        release_year="2025",
        genre="Synthwave",
        thumbnail_url=None,
        audio_formats=[
            AudioFormat(format_id="140", acodec="mp4a.40.2", abr=128.0, ext="m4a")
        ],
    )


def test_tc018_download_queue_sequential_state_transitions(
    tmp_path: Path,
    sample_m4a_path: Path,
) -> None:
    """TC-018 (IR-017, DEC-023, DEC-042):
    Multiple tracks added to queue start at Queued, wait for start_queue(), and transition sequentially
    through Queued -> Downloading -> Completed or Failed (strictly 4 primary statuses).
    """
    url1 = "https://music.youtube.com/watch?v=seq1"
    url2 = "https://music.youtube.com/watch?v=seq2"
    url3_long = "https://music.youtube.com/watch?v=seq3_long"
    tracks = {
        url1: _track(url1, "First Song"),
        url2: _track(url2, "Second Song"),
        # Track 3 has path > 259 chars -> transitions Queued -> Downloading -> Failed (ERR_PATH_TOO_LONG)
        url3_long: RawTrackInfo(
            entry_url=url3_long,
            title="T" * 100,
            artist="A" * 100,
            album="B" * 100,
            album_artist="A" * 100,
            track_number=3,
            disc_number=1,
            release_year="2025",
            genre="Pop",
            thumbnail_url=None,
            audio_formats=[
                AudioFormat(format_id="140", acodec="mp4a.40.2", abr=128.0, ext="m4a")
            ],
        ),
    }

    sd_root = tmp_path / "sdcard"
    sd_root.mkdir()
    config_store = ConfigHistoryStore(base_dir=tmp_path / "app")
    cfg = config_store.load_config()
    cfg["destination_path"] = str(sd_root)
    config_store.save_config(cfg)

    events = EventDispatcher()
    recorded_statuses: dict[str, list[ str]] = {}

    def on_event(event_type: str, data: dict[str, Any]) -> None:
        if event_type == EventDispatcher.EVENT_TASK_STATUS_CHANGED:
            task_dto = data["task"]
            tid = task_dto["task_id"]
            st = task_dto["status"]
            # Enforce IR-017: status must be one of the 4 allowed statuses
            assert st in {"Queued", "Downloading", "Completed", "Failed"}
            recorded_statuses.setdefault(tid, []).append(st)

    events.subscribe(on_event)

    qm = DownloadQueueManager(
        source_adapter=ControllableSourceAdapter(sample_m4a_path, tracks),  # type: ignore[arg-type]
        metadata_service=MetadataAlbumArtService(),
        folder_organizer=SmartFolderOrganizer(),
        audio_processor=FastPassAudioProcessor(),
        output_validator=OutputValidator(),
        sd_card_manager=SDCardManager(drive_probe=FakeDriveProbe(root_dir=sd_root)),
        config_store=config_store,
        event_dispatcher=events,
        temp_root=tmp_path / "temp",
    )

    added = qm.enqueue_url("https://music.youtube.com/playlist?list=PL_SEQ")
    assert len(added) == 3
    # DEC-042: Queue does NOT start automatically before start_queue()
    assert all(t.status == TaskStatus.QUEUED for t in qm.get_tasks())

    qm.start_queue(background=True)
    assert qm.wait_for_idle(timeout=10.0) is True

    t1, t2, t3 = qm.get_tasks()
    assert t1.status == TaskStatus.COMPLETED
    assert t2.status == TaskStatus.COMPLETED
    assert t3.status == TaskStatus.FAILED
    assert t3.error is not None
    assert t3.error.code == ErrorCode.ERR_PATH_TOO_LONG

    assert recorded_statuses[t1.task_id] == ["Downloading", "Completed"]
    assert recorded_statuses[t2.task_id] == ["Downloading", "Completed"]
    assert recorded_statuses[t3.task_id] == ["Downloading", "Failed"]


def test_tc016_cancel_mid_download_cleans_temp_and_sets_failed_err_task_cancelled(
    tmp_path: Path,
    sample_m4a_path: Path,
) -> None:
    """TC-016 (DEC-042):
    Cancelling an in-progress task stops the download, deletes temporary files in Temp,
    sets status to Failed with code ERR_TASK_CANCELLED (recoverable=True), and allows Retry.
    """
    url = "https://music.youtube.com/watch?v=cancel_me"
    tracks = {url: _track(url, "Cancelable Song")}

    sd_root = tmp_path / "sdcard"
    sd_root.mkdir()
    temp_root = tmp_path / "temp"
    config_store = ConfigHistoryStore(base_dir=tmp_path / "app")
    cfg = config_store.load_config()
    cfg["destination_path"] = str(sd_root)
    config_store.save_config(cfg)

    dl_started = Event()
    block_dl = Event()
    adapter = ControllableSourceAdapter(
        sample_m4a=sample_m4a_path,
        tracks_by_url=tracks,
        block_download_event=block_dl,
        download_started_event=dl_started,
    )
    events = EventDispatcher()
    qm = DownloadQueueManager(
        source_adapter=adapter,  # type: ignore[arg-type]
        metadata_service=MetadataAlbumArtService(),
        folder_organizer=SmartFolderOrganizer(),
        audio_processor=FastPassAudioProcessor(),
        output_validator=OutputValidator(),
        sd_card_manager=SDCardManager(drive_probe=FakeDriveProbe(root_dir=sd_root)),
        config_store=config_store,
        event_dispatcher=events,
        temp_root=temp_root,
    )

    task = qm.enqueue_url(url)[0]
    qm.start_queue(background=True)

    # Wait until download_stream has started and written raw_stream.m4a into Temp/<task_id>
    assert dl_started.wait(timeout=5.0) is True
    task_temp_dir = temp_root / task.task_id
    assert task_temp_dir.exists()

    # Cancel the task mid-download
    assert qm.cancel_task(task.task_id) is True
    assert qm.wait_for_idle(timeout=5.0) is True

    assert task.status == TaskStatus.FAILED
    assert task.error is not None
    assert task.error.code == ErrorCode.ERR_TASK_CANCELLED
    assert task.error.recoverable is True
    # Temp directory for the cancelled task must be deleted
    assert not task_temp_dir.exists()
    # Target file must NOT exist on SD card
    assert not (sd_root / "QueueArtist" / "QueueAlbum" / "Cancelable Song.m4a").exists()

    # Verify Retry transitions Failed -> Queued and completes when unblocked
    block_dl.set()
    retried = qm.retry(task.task_id)
    assert retried is not None
    assert retried.status == TaskStatus.QUEUED

    qm.start_queue(background=True)
    assert qm.wait_for_idle(timeout=5.0) is True
    assert task.status == TaskStatus.COMPLETED
    assert (sd_root / "QueueArtist" / "QueueAlbum" / "Cancelable Song.m4a").exists()


def test_tc019_periodic_sdcard_watcher_detects_card_removal_mid_download_and_halts_queue(
    tmp_path: Path,
    sample_m4a_path: Path,
) -> None:
    """TC-019 (DEC-041):
    When the Micro SD Card is removed while a track is downloading, the periodic watcher detects it immediately,
    emits sdcard:status_changed with an alert, marks the current task Failed (ERR_SDCARD_DISCONNECTED),
    cleans up Temp, and halts the queue without crashing or reporting false success.
    """
    url1 = "https://music.youtube.com/watch?v=watch1"
    url2 = "https://music.youtube.com/watch?v=watch2"
    tracks = {
        url1: _track(url1, "Downloading When Unplugged"),
        url2: _track(url2, "Next Queued Song"),
    }

    sd_root = tmp_path / "sdcard"
    sd_root.mkdir()
    temp_root = tmp_path / "temp"
    config_store = ConfigHistoryStore(base_dir=tmp_path / "app")
    cfg = config_store.load_config()
    cfg["destination_path"] = str(sd_root)
    config_store.save_config(cfg)

    dl_started = Event()
    block_dl = Event()
    adapter = ControllableSourceAdapter(
        sample_m4a=sample_m4a_path,
        tracks_by_url=tracks,
        block_download_event=block_dl,
        download_started_event=dl_started,
    )
    probe = FakeDriveProbe(root_dir=sd_root, is_connected=True)
    events = EventDispatcher()
    sd_alerts: list[dict[str, Any]] = []

    def on_event(event_type: str, data: dict[str, Any]) -> None:
        if event_type == EventDispatcher.EVENT_SDCARD_STATUS_CHANGED and data.get("alert"):
            sd_alerts.append(data)

    events.subscribe(on_event)

    qm = DownloadQueueManager(
        source_adapter=adapter,  # type: ignore[arg-type]
        metadata_service=MetadataAlbumArtService(),
        folder_organizer=SmartFolderOrganizer(),
        audio_processor=FastPassAudioProcessor(),
        output_validator=OutputValidator(),
        sd_card_manager=SDCardManager(drive_probe=probe),
        config_store=config_store,
        event_dispatcher=events,
        temp_root=temp_root,
        sd_poll_interval_sec=0.05,  # Fast polling for test
    )

    t1 = qm.enqueue_url(url1)[0]
    t2 = qm.enqueue_url(url2)[0]
    qm.start_queue(background=True)

    # Wait until t1 is actively downloading
    assert dl_started.wait(timeout=5.0) is True

    # Simulate physical removal of Micro SD Card mid-download!
    probe.is_connected = False

    # Watcher should interrupt the download and halt the queue
    assert qm.wait_for_idle(timeout=5.0) is True

    assert t1.status == TaskStatus.FAILED
    assert t1.error is not None
    assert t1.error.code == ErrorCode.ERR_SDCARD_DISCONNECTED
    # t2 must still be Queued because the queue halted on card removal!
    assert t2.status == TaskStatus.QUEUED
    assert len(sd_alerts) >= 1
    assert sd_alerts[0]["alert"]["code"] == ErrorCode.ERR_SDCARD_DISCONNECTED
    assert not (temp_root / t1.task_id).exists()

    # Now reconnect card, unblock download, and call resume_queue() (DEC-042)
    probe.is_connected = True
    block_dl.set()
    qm.resume_queue(background=True)
    assert qm.wait_for_idle(timeout=5.0) is True
    assert t2.status == TaskStatus.COMPLETED


def test_validator_failure_in_queue_prevents_copy_to_sd_card_and_bridge_api_returns_json_dicts(
    tmp_path: Path,
    sample_m4a_path: Path,
) -> None:
    """Verify TC-023 in full pipeline (require_album_art=True with no cover -> Failed, never copied to SD Card) and BridgeAPI methods."""
    url = "https://music.youtube.com/watch?v=nocover"
    tracks = {url: _track(url, "No Cover Track")}

    sd_root = tmp_path / "sdcard"
    sd_root.mkdir()
    config_store = ConfigHistoryStore(base_dir=tmp_path / "app")
    cfg = config_store.load_config()
    cfg["destination_path"] = str(sd_root)
    cfg[CONFIG_KEY_REQUIRE_ALBUM_ART] = True
    config_store.save_config(cfg)

    events = EventDispatcher()
    adapter = ControllableSourceAdapter(sample_m4a_path, tracks)
    sd_mgr = SDCardManager(drive_probe=FakeDriveProbe(root_dir=sd_root))
    qm = DownloadQueueManager(
        source_adapter=adapter,  # type: ignore[arg-type]
        metadata_service=MetadataAlbumArtService(),
        folder_organizer=SmartFolderOrganizer(),
        audio_processor=FastPassAudioProcessor(),
        output_validator=OutputValidator(),
        sd_card_manager=sd_mgr,
        config_store=config_store,
        event_dispatcher=events,
        temp_root=tmp_path / "temp",
    )
    bridge = BridgeAPI(
        queue_manager=qm,
        source_adapter=adapter,  # type: ignore[arg-type]
        sd_card_manager=sd_mgr,
        config_store=config_store,
    )

    # Invalid URL via Bridge returns {"success": False, "error": ...} without raising exception
    bad_res = bridge.enqueue_urls("https://open.spotify.com/track/123")
    assert bad_res["success"] is False
    assert bad_res["error"]["code"] == ErrorCode.ERR_SOURCE_INVALID_URL

    # Enqueue valid URL via Bridge
    enq_res = bridge.enqueue_urls(url)
    assert enq_res["success"] is True
    assert len(enq_res["tasks_added"]) == 1

    # Run queue and verify validator failure prevents copying to SD Card
    qm.start_queue(background=False)
    t = qm.get_tasks()[0]
    assert t.status == TaskStatus.FAILED
    assert t.error is not None
    assert t.error.code == ErrorCode.ERR_VALIDATOR_MISSING_COVER
    assert not (sd_root / "QueueArtist" / "QueueAlbum" / "No Cover Track.m4a").exists()

