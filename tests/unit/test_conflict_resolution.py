"""Unit tests for Conflict Resolution and Apply-to-all scopes in DownloadQueueManager (TC-013, TC-033, DEC-019, DEC-036, DEC-039, DEC-044)."""

from pathlib import Path
import shutil
from threading import Event, Thread
from typing import Any, Optional

from pladaz.bridge.events import EventDispatcher
from pladaz.domain.enums import (
    AudioProcessMode,
    ConflictAction,
    ConflictScope,
    TaskStatus,
)
from pladaz.domain.models import (
    AudioFormat,
    RawSourceEntry,
    RawTrackInfo,
    StreamPlan,
)
from pladaz.services.audio_processor import AudioProcessingService
from pladaz.services.config_store import ConfigHistoryStore
from pladaz.services.folder_organizer import SmartFolderOrganizer
from pladaz.services.metadata_service import MetadataAlbumArtService
from pladaz.services.output_validator import OutputValidator
from pladaz.services.queue_manager import DownloadQueueManager
from pladaz.services.sd_card_manager import SDCardManager
from tests.integration.test_sd_card_manager import FakeDriveProbe


class FakeQueueSourceAdapter:
    """Fake DownloadSourceAdapter tracking whether download_stream was called for each URL."""

    def __init__(
        self,
        sample_m4a: Path,
        tracks_by_url: dict[str, RawTrackInfo],
    ) -> None:
        self.sample_m4a = sample_m4a
        self.tracks_by_url = tracks_by_url
        self.downloaded_urls: list[str] = []

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
                    batch_id="batch-single",
                    index_in_batch=0,
                )
            ]
        # Treat as playlist returning all registered tracks
        return [
            RawSourceEntry(
                entry_url=u,
                title_hint=t.title,
                batch_id="batch-playlist",
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
        self.downloaded_urls.append(entry_url)
        dst = temp_dir / "raw_stream.m4a"
        shutil.copyfile(self.sample_m4a, dst)
        return dst


class FastFakeAudioProcessor(AudioProcessingService):
    """Copies the valid sample M4A directly so unit tests run instantaneously."""

    def to_m4a(
        self,
        input_path: Path,
        output_path: Path,
        mode: AudioProcessMode,
        cancel_event: Optional[Event] = None,
    ) -> Path:
        shutil.copyfile(input_path, output_path)
        return output_path


def _make_track_info(
    url: str,
    title: str,
    album_artist: str,
    album: str,
) -> RawTrackInfo:
    return RawTrackInfo(
        entry_url=url,
        title=title,
        artist=album_artist,
        album=album,
        album_artist=album_artist,
        track_number=1,
        disc_number=1,
        release_year="2025",
        genre="Pop",
        thumbnail_url=None,
        audio_formats=[
            AudioFormat(format_id="140", acodec="mp4a.40.2", abr=128.0, ext="m4a")
        ],
    )


def _setup_queue_manager(
    tmp_path: Path,
    sample_m4a_path: Path,
    tracks_by_url: dict[str, RawTrackInfo],
) -> tuple[
    DownloadQueueManager,
    FakeQueueSourceAdapter,
    EventDispatcher,
    Path,
    ConfigHistoryStore,
]:
    sd_root = tmp_path / "sdcard"
    sd_root.mkdir(parents=True, exist_ok=True)
    app_dir = tmp_path / "app"
    temp_root = tmp_path / "temp"

    config_store = ConfigHistoryStore(base_dir=app_dir)
    cfg = config_store.load_config()
    cfg["destination_path"] = str(sd_root)
    config_store.save_config(cfg)

    events = EventDispatcher()
    adapter = FakeQueueSourceAdapter(sample_m4a_path, tracks_by_url)
    qm = DownloadQueueManager(
        source_adapter=adapter,  # type: ignore[arg-type]
        metadata_service=MetadataAlbumArtService(),
        folder_organizer=SmartFolderOrganizer(),
        audio_processor=FastFakeAudioProcessor(),
        output_validator=OutputValidator(),
        sd_card_manager=SDCardManager(drive_probe=FakeDriveProbe(root_dir=sd_root)),
        config_store=config_store,
        event_dispatcher=events,
        temp_root=temp_root,
        sd_poll_interval_sec=0.2,
    )
    return qm, adapter, events, sd_root, config_store


def test_tc013_conflict_prompt_before_audio_download_overwrite_skip_and_keep_both(
    tmp_path: Path,
    sample_m4a_path: Path,
) -> None:
    """TC-013 (DEC-019, DEC-036, DEC-039):
    - Conflict check happens BEFORE downloading audio.
    - Skip: removes task from queue immediately, does NOT download audio, does NOT add to history, and does NOT create a 5th status.
    - Keep Both: saves as '<Title> (1).m4a'.
    - Overwrite: replaces existing file on SD card.
    """
    url1 = "https://music.youtube.com/watch?v=dup1"
    url2 = "https://music.youtube.com/watch?v=dup2"
    url3 = "https://music.youtube.com/watch?v=dup3"
    tracks = {
        url1: _make_track_info(url1, "SameSong", "ArtistX", "AlbumX"),
        url2: _make_track_info(url2, "SameSong", "ArtistX", "AlbumX"),
        url3: _make_track_info(url3, "SameSong", "ArtistX", "AlbumX"),
    }
    qm, adapter, events, sd_root, config_store = _setup_queue_manager(
        tmp_path, sample_m4a_path, tracks
    )

    # Pre-create existing file on SD card
    existing_file = sd_root / "ArtistX" / "AlbumX" / "SameSong.m4a"
    existing_file.parent.mkdir(parents=True, exist_ok=True)
    existing_file.write_bytes(b"OLD_FILE_BYTES")

    actions_to_apply = [
        ConflictAction.SKIP,
        ConflictAction.KEEP_BOTH,
        ConflictAction.OVERWRITE,
    ]
    prompted_tasks: list[str] = []
    download_count_at_prompt: list[int] = []

    def on_event(event_type: str, data: dict[str, Any]) -> None:
        if event_type == EventDispatcher.EVENT_TASK_CONFLICT_PROMPT:
            tid = data["task_id"]
            prompted_tasks.append(tid)
            # Verify that at the moment of conflict prompt, download_stream has NOT been called for this task!
            download_count_at_prompt.append(len(adapter.downloaded_urls))
            action = actions_to_apply.pop(0)
            Thread(
                target=lambda: qm.resolve_conflict(tid, action, ConflictScope.SINGLE),
                daemon=True,
            ).start()

    events.subscribe(on_event)

    t1 = qm.enqueue_url(url1)[0]
    t2 = qm.enqueue_url(url2)[0]
    t3 = qm.enqueue_url(url3)[0]

    qm.start_queue(background=True)
    assert qm.wait_for_idle(timeout=10.0) is True

    # All 3 prompted before their respective downloads
    assert prompted_tasks == [t1.task_id, t2.task_id, t3.task_id]
    # Task 1 was skipped -> download count was 0 at prompt 1 AND still 0 at prompt 2!
    assert download_count_at_prompt == [0, 0, 1]
    assert adapter.downloaded_urls == [url2, url3]

    # Task 1 (Skip) was removed from queue and NOT recorded in history.json
    remaining_ids = [t.task_id for t in qm.get_tasks()]
    assert t1.task_id not in remaining_ids
    assert t2.task_id in remaining_ids
    assert t3.task_id in remaining_ids

    history_ids = [h.task_id for h in config_store.load_history()]
    assert t1.task_id not in history_ids
    assert t2.task_id in history_ids
    assert t3.task_id in history_ids

    # Task 2 (Keep Both) created 'SameSong (1).m4a'
    keep_both_file = sd_root / "ArtistX" / "AlbumX" / "SameSong (1).m4a"
    assert keep_both_file.exists()

    # Task 3 (Overwrite) replaced 'SameSong.m4a' with valid M4A content
    assert existing_file.exists()
    assert existing_file.read_bytes() != b"OLD_FILE_BYTES"


def test_tc033a_apply_to_all_in_this_album_only_affects_same_album_folder(
    tmp_path: Path,
    sample_m4a_path: Path,
) -> None:
    """TC-033(a) (DEC-044):
    Selecting 'Apply to all in this album' applies automatically to other conflicting tracks targeting the same
    sanitized <Album Artist>/<Album> folder (Album A), while conflicting tracks in Album B still trigger a Conflict Prompt.
    """
    url_a1 = "https://music.youtube.com/watch?v=a1"
    url_a2 = "https://music.youtube.com/watch?v=a2"
    url_b1 = "https://music.youtube.com/watch?v=b1"
    tracks = {
        url_a1: _make_track_info(url_a1, "Track1", "ArtistA", "AlbumA"),
        url_a2: _make_track_info(url_a2, "Track2", "ArtistA", "AlbumA"),
        url_b1: _make_track_info(url_b1, "TrackB1", "ArtistA", "AlbumB"),
    }
    qm, adapter, events, sd_root, _ = _setup_queue_manager(
        tmp_path, sample_m4a_path, tracks
    )

    # Pre-create conflicting files for all 3 tracks
    for artist, album, name in [
        ("ArtistA", "AlbumA", "Track1.m4a"),
        ("ArtistA", "AlbumA", "Track2.m4a"),
        ("ArtistA", "AlbumB", "TrackB1.m4a"),
    ]:
        p = sd_root / artist / album / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"EXISTING")

    prompted_task_ids: list[str] = []

    def on_event(event_type: str, data: dict[str, Any]) -> None:
        if event_type == EventDispatcher.EVENT_TASK_CONFLICT_PROMPT:
            tid = data["task_id"]
            prompted_task_ids.append(tid)
            if len(prompted_task_ids) == 1:
                # First prompt (Album A Track 1): choose KEEP_BOTH with scope ALBUM
                Thread(
                    target=lambda: qm.resolve_conflict(
                        tid, ConflictAction.KEEP_BOTH, ConflictScope.ALBUM
                    ),
                    daemon=True,
                ).start()
            else:
                # Second prompt must be Album B Track B1: choose SKIP with scope SINGLE
                Thread(
                    target=lambda: qm.resolve_conflict(
                        tid, ConflictAction.SKIP, ConflictScope.SINGLE
                    ),
                    daemon=True,
                ).start()

    events.subscribe(on_event)

    ta1 = qm.enqueue_url(url_a1)[0]
    ta2 = qm.enqueue_url(url_a2)[0]
    tb1 = qm.enqueue_url(url_b1)[0]

    qm.start_queue(background=True)
    assert qm.wait_for_idle(timeout=10.0) is True

    # Album A Track 2 must NOT have prompted; only ta1 and tb1 prompted!
    assert prompted_task_ids == [ta1.task_id, tb1.task_id]
    assert (sd_root / "ArtistA" / "AlbumA" / "Track1 (1).m4a").exists()
    assert (sd_root / "ArtistA" / "AlbumA" / "Track2 (1).m4a").exists()
    # Album B Track B1 was skipped -> not downloaded
    assert url_b1 not in adapter.downloaded_urls


def test_tc033b_apply_to_all_in_queue_covers_newly_added_tasks_and_resets_when_queue_empties(
    tmp_path: Path,
    sample_m4a_path: Path,
) -> None:
    """TC-033(b) (DEC-044):
    'Apply to all in queue' applies to all conflicting tasks in the current queue run, INCLUDING tasks added while the queue
    is still active, and resets once the queue becomes empty.
    """
    url1 = "https://music.youtube.com/watch?v=q1"
    url2 = "https://music.youtube.com/watch?v=q2"
    url3_late = "https://music.youtube.com/watch?v=q3_late"
    url4_next_run = "https://music.youtube.com/watch?v=q4_next_run"
    tracks = {
        url1: _make_track_info(url1, "Song1", "Art1", "Alb1"),
        url2: _make_track_info(url2, "Song2", "Art2", "Alb2"),
        url3_late: _make_track_info(url3_late, "Song3", "Art3", "Alb3"),
        url4_next_run: _make_track_info(url4_next_run, "Song4", "Art4", "Alb4"),
    }
    qm, adapter, events, sd_root, _ = _setup_queue_manager(
        tmp_path, sample_m4a_path, tracks
    )

    for info in tracks.values():
        p = sd_root / str(info.album_artist) / str(info.album) / f"{info.title}.m4a"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"EXISTING")

    prompted_task_ids: list[str] = []

    def on_event(event_type: str, data: dict[str, Any]) -> None:
        if event_type == EventDispatcher.EVENT_TASK_CONFLICT_PROMPT:
            tid = data["task_id"]
            prompted_task_ids.append(tid)
            if len(prompted_task_ids) == 1:
                # While task 1 is waiting at conflict prompt, enqueue url3_late into the active queue!
                qm.enqueue_url(url3_late)
                # Resolve task 1 with SKIP + QUEUE scope
                Thread(
                    target=lambda: qm.resolve_conflict(
                        tid, ConflictAction.SKIP, ConflictScope.QUEUE
                    ),
                    daemon=True,
                ).start()
            else:
                # Next queue run after reset -> resolve with KEEP_BOTH
                Thread(
                    target=lambda: qm.resolve_conflict(
                        tid, ConflictAction.KEEP_BOTH, ConflictScope.SINGLE
                    ),
                    daemon=True,
                ).start()

    events.subscribe(on_event)

    t1 = qm.enqueue_url(url1)[0]
    qm.enqueue_url(url2)

    qm.start_queue(background=True)
    assert qm.wait_for_idle(timeout=10.0) is True

    # Run 1: Only t1 prompted; t2 and t3_late were automatically skipped by the QUEUE rule!
    assert prompted_task_ids == [t1.task_id]
    assert adapter.downloaded_urls == []
    assert qm.get_tasks() == []

    # Run 2 (after queue became empty, rule must have reset!): enqueue url4_next_run
    t4 = qm.enqueue_url(url4_next_run)[0]
    qm.start_queue(background=True)
    assert qm.wait_for_idle(timeout=10.0) is True

    # Because queue became empty after Run 1, t4 MUST trigger a new Conflict Prompt!
    assert prompted_task_ids == [t1.task_id, t4.task_id]
    assert (sd_root / "Art4" / "Alb4" / "Song4 (1).m4a").exists()

