"""JSON-serializable DTO converters for crossing the pywebview Bridge (SYSTEM_DESIGN.md 2.3)."""

from typing import Any, Optional

from pladaz.domain.models import (
    HistoryEntry,
    SDCardStatus,
    StructuredError,
    TrackMetadata,
    TrackTask,
)


def structured_error_to_dto(
    err: Optional[StructuredError],
) -> Optional[dict[str, Any]]:
    """Convert StructuredError into a JSON-serializable dict."""
    if err is None:
        return None
    return {
        "code": err.code,
        "message_en": err.message_en,
        "recoverable": bool(err.recoverable),
        "task_id": err.task_id,
        "details": err.details,
    }


def metadata_to_dto(meta: Optional[TrackMetadata]) -> Optional[dict[str, Any]]:
    """Convert TrackMetadata into a JSON-serializable dict without cover_jpeg bytes (SYSTEM_DESIGN.md 2.3)."""
    if meta is None:
        return None
    return {
        "title": meta.title,
        "track_artist": meta.track_artist,
        "album": meta.album,
        "album_artist": meta.album_artist,
        "track_number": meta.track_number,
        "total_tracks": meta.total_tracks,
        "disc_number": meta.disc_number,
        "total_discs": meta.total_discs,
        "year": meta.year,
        "genre": meta.genre,
        "has_cover": bool(meta.cover_jpeg),
    }


def task_to_dto(task: TrackTask) -> dict[str, Any]:
    """Convert TrackTask into TaskDTO using only primitive JSON types (SYSTEM_DESIGN.md 2.3)."""
    return {
        "task_id": task.task_id,
        "entry_url": task.entry_url,
        "batch_id": task.batch_id,
        "status": task.status.value,
        "stage": task.stage.value if task.stage is not None else None,
        "progress_percent": float(task.progress_percent),
        "metadata": metadata_to_dto(task.metadata),
        "temp_file_path": str(task.temp_file_path) if task.temp_file_path else None,
        "target_file_path": str(task.target_file_path) if task.target_file_path else None,
        "has_cover": bool(task.metadata and task.metadata.cover_jpeg),
        "warnings": list(task.warnings),
        "error": structured_error_to_dto(task.error),
        "validation": (
            {
                "is_valid": bool(task.validation_result.is_valid),
                "is_readable": bool(task.validation_result.is_readable),
                "is_aac_lc": bool(task.validation_result.is_aac_lc),
                "has_title": bool(task.validation_result.has_title),
                "has_cover": bool(task.validation_result.has_cover),
                "error_code": task.validation_result.error_code,
            }
            if task.validation_result is not None
            else None
        ),
    }


def sdcard_status_to_dto(status: SDCardStatus) -> dict[str, Any]:
    """Convert SDCardStatus into SDCardDTO."""
    return {
        "drive_root": status.drive_root,
        "destination_dir": status.destination_dir,
        "is_connected": bool(status.is_connected),
        "is_writable": bool(status.is_writable),
        "free_bytes": int(status.free_bytes),
        "total_bytes": int(status.total_bytes),
        "volume_label": status.volume_label,
    }


def history_entry_to_dto(entry: HistoryEntry) -> dict[str, Any]:
    """Convert HistoryEntry into HistoryEntryDTO."""
    return {
        "task_id": entry.task_id,
        "finished_at": entry.finished_at,
        "status": entry.status.value,
        "title": entry.title,
        "album_artist": entry.album_artist,
        "album": entry.album,
        "target_file_path": entry.target_file_path,
        "source_url": entry.source_url,
        "warnings": list(entry.warnings),
        "error_code": entry.error_code,
    }

