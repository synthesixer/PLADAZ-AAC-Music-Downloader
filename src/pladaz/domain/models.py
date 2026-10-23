"""Domain data models strictly matching SYSTEM_DESIGN.md Section 2.2."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pladaz.domain.enums import AudioProcessMode, Stage, TaskStatus


@dataclass
class TrackMetadata:
    """9 fields per Plan 2.1. None = leave empty in tags (Plan 7.3: never write fake values)."""

    title: str
    track_artist: Optional[str] = None
    album: Optional[str] = None
    album_artist: Optional[str] = None
    track_number: Optional[int] = None
    total_tracks: Optional[int] = None
    disc_number: Optional[int] = None
    total_discs: Optional[int] = None
    year: Optional[str] = None
    genre: Optional[str] = None
    cover_jpeg: Optional[bytes] = None


@dataclass
class RawSourceEntry:
    """Lightweight entry from flat URL extraction (no formats)."""

    entry_url: str
    title_hint: Optional[str] = None
    batch_id: str = ""
    index_in_batch: int = 0


@dataclass
class AudioFormat:
    """Single audio format descriptor from yt-dlp."""

    format_id: str
    acodec: str
    abr: Optional[float]
    ext: str
    # 'none' for audio-only streams; None when yt-dlp did not report it
    vcodec: Optional[str] = None


@dataclass
class RawTrackInfo:
    """Full track info from yt-dlp including metadata and formats."""

    entry_url: str
    title: Optional[str]
    artist: Optional[str]
    album: Optional[str]
    album_artist: Optional[str]
    track_number: Optional[int]
    disc_number: Optional[int]
    release_year: Optional[str]
    genre: Optional[str]
    thumbnail_url: Optional[str]
    audio_formats: list[AudioFormat]


@dataclass
class StreamPlan:
    """Planned audio stream selection and processing mode."""

    format_id: str
    mode: AudioProcessMode


@dataclass
class ExternalMetadata:
    """Single candidate result from iTunes/MusicBrainz Search API."""

    source: str
    title: str
    artist: str
    album: Optional[str] = None
    album_artist: Optional[str] = None
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    genre: Optional[str] = None
    year: Optional[str] = None
    cover_url: Optional[str] = None


@dataclass
class UpdateResult:
    """Result of yt-dlp.exe update operation."""

    success: bool
    old_version: Optional[str]
    new_version: Optional[str]
    message: str


@dataclass
class ValidationResult:
    """Result returned by OutputValidator.validate()."""

    is_valid: bool
    is_readable: bool = False
    is_aac_lc: bool = False
    has_title: bool = False
    has_cover: bool = False
    warnings: list[str] = field(default_factory=list)
    error_code: Optional[str] = None


@dataclass
class SDCardStatus:
    """Status of a storage drive / destination directory."""

    drive_root: str
    destination_dir: str
    is_connected: bool
    is_writable: bool
    free_bytes: int
    total_bytes: int
    volume_label: Optional[str] = None


@dataclass
class StructuredError:
    """Structured error object with English UI message (DEC-025) and no cookies data."""

    code: str
    message_en: str
    recoverable: bool
    task_id: Optional[str] = None
    details: Optional[str] = None


@dataclass
class TrackTask:
    """Internal Core task entity (never sent directly across Bridge; use TaskDTO in Phase 4)."""

    task_id: str
    entry_url: str
    batch_id: str
    status: TaskStatus = TaskStatus.QUEUED
    stage: Optional[Stage] = None
    progress_percent: float = 0.0
    metadata: Optional[TrackMetadata] = None
    temp_file_path: Optional[Path] = None
    target_file_path: Optional[Path] = None
    warnings: list[str] = field(default_factory=list)
    error: Optional[StructuredError] = None
    validation_result: Optional[ValidationResult] = None


@dataclass
class HistoryEntry:
    """Entry persisted in history.json (only completed or failed tasks)."""

    task_id: str
    finished_at: str
    status: TaskStatus
    title: Optional[str]
    album_artist: Optional[str]
    album: Optional[str]
    target_file_path: Optional[str]
    source_url: str
    warnings: list[str] = field(default_factory=list)
    error_code: Optional[str] = None
    # None when no metadata was resolved (e.g. failed before fetching info) or for entries written before this field existed
    has_cover: Optional[bool] = None

