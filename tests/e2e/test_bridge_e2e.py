"""End-to-End tests through BridgeAPI (Plan 9.1, TC-018, TC-004, TC-005, TC-006, TC-007, TC-014, TC-015)."""

import os
from pathlib import Path
import shutil
import time
from typing import Any, Optional
import pytest
from mutagen.mp4 import MP4, MP4Cover
from PIL import Image

from pladaz.bridge.api import BridgeAPI
from pladaz.bridge.events import EventDispatcher
from pladaz.domain.enums import AudioProcessMode, TaskStatus
from pladaz.domain.models import (
    AudioFormat,
    RawSourceEntry,
    RawTrackInfo,
    StreamPlan,
)
from pladaz.services.audio_processor import AudioProcessingService
from pladaz.services.config_store import ConfigHistoryStore
from pladaz.services.folder_organizer import SmartFolderOrganizer
from pladaz.services.logger import PladazLogger
from pladaz.services.metadata_service import MetadataAlbumArtService
from pladaz.services.output_validator import OutputValidator
from pladaz.services.queue_manager import DownloadQueueManager
from pladaz.services.sd_card_manager import SDCardManager
from pladaz.services.source_adapter import DownloadSourceAdapter

pytestmark = [pytest.mark.e2e, pytest.mark.integration]


class MockExternalFetcher:
    """Mock external fetcher providing test cover image bytes."""

    def __init__(self, cover_bytes: bytes) -> None:
        self._cover_bytes = cover_bytes

    def fetch_cover_bytes(self, url: str) -> bytes:
        return self._cover_bytes

    def search_itunes(self, term: str) -> list[Any]:
        return []

    def search_musicbrainz(self, query: str) -> list[Any]:
        return []


class MockE2ESourceAdapter(DownloadSourceAdapter):
    """Adapter for offline E2E pipeline simulation using real audio and cover files."""

    def __init__(self, sample_m4a: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._sample_m4a = sample_m4a

    def extract_entries(
        self,
        url: str,
        cookies_path: Optional[Path] = None,
    ) -> list[RawSourceEntry]:
        if "playlist" in url or "album" in url:
            return [
                RawSourceEntry(
                    entry_url=f"{url}&index=1",
                    title_hint="Track One",
                ),
                RawSourceEntry(
                    entry_url=f"{url}&index=2",
                    title_hint="Track Two",
                ),
            ]
        return [
            RawSourceEntry(
                entry_url=url,
                title_hint="E2E Solo Track",
            )
        ]

    def fetch_track_info(
        self,
        url: str,
        cookies_path: Optional[Path] = None,
    ) -> RawTrackInfo:
        is_solo = "solo" in url.lower() or "single" in url.lower()
        title = "E2E Solo Track" if is_solo else "Track One"
        artist = "Featured Artist" if is_solo else "E2E Artist"
        album_artist = "Main Album Artist" if is_solo else "E2E Artist"
        album = "Solo Album" if is_solo else "E2E Album"

        return RawTrackInfo(
            entry_url=url,
            title=title,
            artist=artist,
            album=album,
            album_artist=album_artist,
            track_number=1,
            disc_number=1,
            release_year="2026",
            genre="Electronic / Ambient",
            thumbnail_url="http://mock.thumb/cover.png",
            audio_formats=[
                AudioFormat(format_id="140", acodec="mp4a.40.2", abr=128.0, ext="m4a"),
            ],
        )

    def plan_stream(self, info: RawTrackInfo) -> StreamPlan:
        return StreamPlan(
            format_id="140",
            mode=AudioProcessMode.REMUX_AAC,
        )

    def download_stream(
        self,
        entry_url: str,
        plan: StreamPlan,
        temp_dir: Path,
        progress_cb: Any = None,
        cancel_event: Any = None,
        cookies_path: Optional[Path] = None,
    ) -> Path:
        dest_path = Path(temp_dir) / "raw_stream.m4a"
        shutil.copyfile(self._sample_m4a, dest_path)
        return dest_path


def test_bridge_e2e_full_queue_workflow_and_atom_verification(
    tmp_path: Path,
    sample_m4a_path: Path,
    sample_wide_png_bytes: bytes,
) -> None:
    """E2E test through BridgeAPI from enqueue to file writing on simulated SD card (TC-018, TC-004..007, TC-014, TC-015)."""
    app_root = tmp_path / "app"
    sd_root = tmp_path / "simulated_sd"
    temp_root = tmp_path / "temp"

    app_root.mkdir(parents=True)
    sd_root.mkdir(parents=True)
    temp_root.mkdir(parents=True)

    logger = PladazLogger(log_dir=app_root / "logs")
    config_store = ConfigHistoryStore(base_dir=app_root, logger=logger)
    events = EventDispatcher()
    sd_card_manager = SDCardManager(logger=logger)
    folder_organizer = SmartFolderOrganizer()
    metadata_service = MetadataAlbumArtService(
        external_fetcher=MockExternalFetcher(sample_wide_png_bytes),
        logger=logger,
    )
    audio_processor = AudioProcessingService(logger=logger)
    output_validator = OutputValidator()

    mock_source = MockE2ESourceAdapter(
        sample_m4a=sample_m4a_path,
        ytdlp_path=Path("yt-dlp.exe"),
        logger=logger,
    )

    queue_manager = DownloadQueueManager(
        source_adapter=mock_source,
        metadata_service=metadata_service,
        folder_organizer=folder_organizer,
        audio_processor=audio_processor,
        output_validator=output_validator,
        sd_card_manager=sd_card_manager,
        config_store=config_store,
        event_dispatcher=events,
        temp_root=temp_root,
        logger=logger,
        clean_temp_on_init=True,
    )

    bridge = BridgeAPI(
        queue_manager=queue_manager,
        source_adapter=mock_source,
        sd_card_manager=sd_card_manager,
        config_store=config_store,
        log_file_path=app_root / "logs" / "pladaz.log",
        ffmpeg_path=Path("ffmpeg.exe"),
    )

    # 1. Set destination path through Bridge
    save_res = bridge.update_config({"destination_path": str(sd_root)})
    assert save_res["success"] is True

    # 2. Enqueue track through BridgeAPI (takes multiline string)
    enqueue_res = bridge.enqueue_urls("https://www.youtube.com/watch?v=solo_test_track")
    assert enqueue_res["success"] is True, f"Enqueue failed: {enqueue_res}"
    assert len(enqueue_res["tasks_added"]) == 1

    # Verify queue state
    initial_queue = queue_manager.get_tasks()
    assert len(initial_queue) == 1
    assert initial_queue[0].status == TaskStatus.QUEUED

    # 3. Start Queue
    start_res = bridge.start_queue()
    assert start_res["success"] is True

    # Wait for queue worker to complete (sequential execution)
    deadline = time.time() + 10.0
    while time.time() < deadline:
        tasks = queue_manager.get_tasks()
        if tasks and tasks[0].status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            break
        time.sleep(0.1)

    final_queue = queue_manager.get_tasks()
    assert final_queue[0].status == TaskStatus.COMPLETED, f"Task did not complete: {final_queue[0].error}"

    # 4. Verify target folder structure: <sd_root>/<Album Artist>/<Album>/<Title>.m4a
    expected_file = (
        sd_root / "Main Album Artist" / "Solo Album" / "E2E Solo Track.m4a"
    )
    assert expected_file.exists(), f"Expected file not found at {expected_file}"
    assert expected_file.stat().st_size > 0

    # 5. Verify MP4 Atoms and tags with mutagen (TC-004, TC-005, TC-006, TC-007, TC-015)
    mp4 = MP4(expected_file)

    # Recorded Atom verification:
    # ©nam = Title
    assert mp4.tags.get("\xa9nam") == ["E2E Solo Track"]
    # ©ART = Track Artist
    assert mp4.tags.get("\xa9ART") == ["Featured Artist"]
    # aART = Album Artist
    assert mp4.tags.get("aART") == ["Main Album Artist"]
    # ©alb = Album
    assert mp4.tags.get("\xa9alb") == ["Solo Album"]
    # trkn = Track Number tuple (track, total)
    assert mp4.tags.get("trkn") == [(1, 0)]
    # disk = Disc Number tuple (disc, total)
    assert mp4.tags.get("disk") == [(1, 0)]
    # ©day = Release Year
    assert mp4.tags.get("\xa9day") == ["2026"]
    # ©gen = Genre
    assert mp4.tags.get("\xa9gen") == ["Electronic / Ambient"]

    # covr = 800x800 JPEG byte verification
    covers = mp4.tags.get("covr")
    assert covers is not None and len(covers) > 0
    cover_data = covers[0]
    assert isinstance(cover_data, MP4Cover)
    assert cover_data.imageformat == MP4Cover.FORMAT_JPEG

    # Verify image dimensions with Pillow
    cover_io = Path(tmp_path / "read_back_cover.jpg")
    cover_io.write_bytes(cover_data)
    with Image.open(cover_io) as im:
        assert im.format == "JPEG"
        assert im.size == (800, 800)

    # 6. Verify History persistence in history.json
    history_res = bridge.get_history()
    assert history_res["success"] is True
    history_items = history_res["entries"]
    assert len(history_items) == 1
    assert history_items[0]["title"] == "E2E Solo Track"
    assert history_items[0]["album_artist"] == "Main Album Artist"
    assert history_items[0]["album"] == "Solo Album"
    assert history_items[0]["status"] == "Completed"

    # Clean shutdown
    for t in queue_manager.get_tasks():
        queue_manager.cancel_task(t.task_id)
    queue_manager.cleanup_all_temp()
    logger.close()


@pytest.mark.network
def test_bridge_e2e_live_network_download(tmp_path: Path) -> None:
    """Live network E2E test using actual YouTube URLs provided via PLADAZ_TEST_URLS env var."""
    raw_urls = os.environ.get("PLADAZ_TEST_URLS")
    if not raw_urls or not raw_urls.strip():
        pytest.skip(
            "TC-024 live network test requires PLADAZ_TEST_URLS environment variable with test URLs."
        )

    urls = [u.strip() for u in raw_urls.split(",") if u.strip()]
    app_root = tmp_path / "app"
    sd_root = tmp_path / "dest"
    app_root.mkdir(parents=True)
    sd_root.mkdir(parents=True)

    logger = PladazLogger(log_dir=app_root / "logs")
    config_store = ConfigHistoryStore(base_dir=app_root, logger=logger)
    events = EventDispatcher()
    sd_card_manager = SDCardManager(logger=logger)
    folder_organizer = SmartFolderOrganizer()
    metadata_service = MetadataAlbumArtService(logger=logger)
    audio_processor = AudioProcessingService(logger=logger)
    output_validator = OutputValidator()
    source_adapter = DownloadSourceAdapter(ytdlp_path=Path("yt-dlp.exe"), logger=logger)

    queue_manager = DownloadQueueManager(
        source_adapter=source_adapter,
        metadata_service=metadata_service,
        folder_organizer=folder_organizer,
        audio_processor=audio_processor,
        output_validator=output_validator,
        sd_card_manager=sd_card_manager,
        config_store=config_store,
        event_dispatcher=events,
        temp_root=tmp_path / "temp",
        logger=logger,
        clean_temp_on_init=True,
    )

    bridge = BridgeAPI(
        queue_manager=queue_manager,
        source_adapter=source_adapter,
        sd_card_manager=sd_card_manager,
        config_store=config_store,
        log_file_path=app_root / "logs" / "pladaz.log",
        ffmpeg_path=Path("ffmpeg.exe"),
    )

    bridge.update_config({"destination_path": str(sd_root)})
    enqueue_res = bridge.enqueue_urls("\n".join(urls))
    assert enqueue_res["success"] is True

    bridge.start_queue()
    # Wait for completion with timeout
    deadline = time.time() + 180.0
    while time.time() < deadline:
        tasks = queue_manager.get_tasks()
        active = any(t.status in (TaskStatus.QUEUED, TaskStatus.DOWNLOADING) for t in tasks)
        if not active:
            break
        time.sleep(1.0)

    for t in queue_manager.get_tasks():
        queue_manager.cancel_task(t.task_id)
    queue_manager.cleanup_all_temp()
    logger.close()
