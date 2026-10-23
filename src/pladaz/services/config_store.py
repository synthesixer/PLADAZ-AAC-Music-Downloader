"""Portable JSON configuration and history store (SYSTEM_DESIGN.md 2.5(7), DEC-023, TC-029, TC-030)."""

from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Optional

from pladaz.domain.enums import TaskStatus
from pladaz.domain.errors import ErrorCode
from pladaz.domain.models import HistoryEntry, StructuredError
from pladaz.services.logger import PladazLogger

# [Proposal] Key name for cover art requirement switch in config.json (SYSTEM_DESIGN.md 2.5(5) & (7))
# Isolated in a single constant so it can be updated in one place if changed later.
CONFIG_KEY_REQUIRE_ALBUM_ART: str = "require_album_art"
CONFIG_KEY_MUSICBRAINZ_USER_AGENT: str = "musicbrainz_user_agent"

SCHEMA_VERSION: int = 1


def get_default_config() -> dict[str, Any]:
    """Return a fresh copy of the default config.json dictionary (SYSTEM_DESIGN.md 2.5(7))."""
    return {
        "schema_version": SCHEMA_VERSION,
        "disclaimer_accepted": False,
        "destination_path": "",
        "cookies_file_path": None,
        CONFIG_KEY_REQUIRE_ALBUM_ART: False,
        CONFIG_KEY_MUSICBRAINZ_USER_AGENT: "",
    }


def get_default_history_payload() -> dict[str, Any]:
    """Return a fresh copy of the default history.json dictionary (SYSTEM_DESIGN.md 2.5(7))."""
    return {
        "schema_version": SCHEMA_VERSION,
        "entries": [],
    }


class ConfigHistoryStore:
    """Manages portable config.json and history.json with atomic writes and corrupt-file recovery."""

    def __init__(
        self,
        base_dir: Path,
        logger: Optional[PladazLogger] = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.base_dir / "config.json"
        self.history_path = self.base_dir / "history.json"
        self._logger = logger
        self.last_error: Optional[StructuredError] = None
        # Serializes reads and writes: the queue worker and Bridge calls touch these files from different threads
        self._lock = RLock()

    def _atomic_write_json(self, target_path: Path, data: dict[str, Any]) -> None:
        """Write JSON to a temporary file, flush + fsync, then atomically replace target_path."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target_path.with_name(f"{target_path.name}.tmp")
        serialized = json.dumps(data, indent=2, ensure_ascii=False)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(serialized)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target_path)

    def _backup_corrupt_file(self, target_path: Path, reason: str) -> Path:
        """Rename a corrupted JSON file to *.corrupt-<timestamp> and record ERR_CONFIG_CORRUPT."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        backup_path = target_path.with_name(f"{target_path.name}.corrupt-{timestamp}")
        counter = 1
        while backup_path.exists():
            backup_path = target_path.with_name(
                f"{target_path.name}.corrupt-{timestamp}-{counter}"
            )
            counter += 1

        try:
            os.replace(target_path, backup_path)
        except OSError:
            pass

        err_msg = (
            f"Configuration file '{target_path.name}' was corrupted and has been reset to defaults. "
            f"Backup saved as '{backup_path.name}'."
        )
        self.last_error = StructuredError(
            code=ErrorCode.ERR_CONFIG_CORRUPT,
            message_en=err_msg,
            recoverable=True,
            details=reason,
        )
        if self._logger:
            self._logger.error(
                component="ConfigHistoryStore",
                message=f"{err_msg} ({reason})",
                error_code=ErrorCode.ERR_CONFIG_CORRUPT,
            )
        return backup_path

    def load_config(self) -> dict[str, Any]:
        """Load config.json, creating or resetting to defaults if missing or corrupted (TC-030)."""
        with self._lock:
            defaults = get_default_config()
            if not self.config_path.exists():
                self._atomic_write_json(self.config_path, defaults)
                return dict(defaults)

            try:
                raw_text = self.config_path.read_text(encoding="utf-8")
                parsed = json.loads(raw_text)
                if not isinstance(parsed, dict):
                    raise ValueError("Root of config.json must be a JSON object.")
                # Validate types of core fields if present
                if "disclaimer_accepted" in parsed and not isinstance(
                    parsed["disclaimer_accepted"], bool
                ):
                    raise ValueError("'disclaimer_accepted' must be a boolean.")
                if (
                    CONFIG_KEY_REQUIRE_ALBUM_ART in parsed
                    and not isinstance(parsed[CONFIG_KEY_REQUIRE_ALBUM_ART], bool)
                ):
                    raise ValueError(f"'{CONFIG_KEY_REQUIRE_ALBUM_ART}' must be a boolean.")
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                self._backup_corrupt_file(self.config_path, str(exc))
                self._atomic_write_json(self.config_path, defaults)
                return dict(defaults)

            merged = dict(defaults)
            merged.update(parsed)
            return merged

    def save_config(self, cfg: dict[str, Any]) -> None:
        """Save configuration dictionary atomically to config.json."""
        with self._lock:
            merged = get_default_config()
            merged.update(cfg)
            self._atomic_write_json(self.config_path, merged)

    def load_history(self) -> list[HistoryEntry]:
        """Load history.json entries, resetting and backing up if corrupted (TC-030)."""
        with self._lock:
            default_payload = get_default_history_payload()
            if not self.history_path.exists():
                self._atomic_write_json(self.history_path, default_payload)
                return []

            try:
                raw_text = self.history_path.read_text(encoding="utf-8")
                parsed = json.loads(raw_text)
                if not isinstance(parsed, dict) or not isinstance(
                    parsed.get("entries"), list
                ):
                    raise ValueError(
                        "history.json must be a JSON object with an 'entries' list."
                    )
                entries: list[HistoryEntry] = []
                for item in parsed["entries"]:
                    if not isinstance(item, dict):
                        raise ValueError("Each history entry must be a JSON object.")
                    status_val = TaskStatus(item["status"])
                    entries.append(
                        HistoryEntry(
                            task_id=str(item["task_id"]),
                            finished_at=str(item["finished_at"]),
                            status=status_val,
                            title=item.get("title"),
                            album_artist=item.get("album_artist"),
                            album=item.get("album"),
                            target_file_path=item.get("target_file_path"),
                            source_url=str(item["source_url"]),
                            warnings=list(item.get("warnings", [])),
                            error_code=item.get("error_code"),
                            has_cover=item.get("has_cover"),
                        )
                    )
                return entries
            except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
                self._backup_corrupt_file(self.history_path, str(exc))
                self._atomic_write_json(self.history_path, default_payload)
                return []

    def append_history(self, entry: HistoryEntry) -> None:
        """Append a finished task (Completed or Failed) to history.json atomically."""
        with self._lock:
            if entry.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                raise ValueError(
                    f"Only Completed or Failed tasks may be stored in history.json, got: {entry.status}"
                )
            current_entries = self.load_history()
            current_entries.append(entry)
            serialized_entries: list[dict[str, Any]] = []
            for item in current_entries:
                d = asdict(item)
                d["status"] = item.status.value
                serialized_entries.append(d)
            payload = {
                "schema_version": SCHEMA_VERSION,
                "entries": serialized_entries,
            }
            self._atomic_write_json(self.history_path, payload)

    def clear_history(self) -> None:
        """Clear all entries in history.json atomically (Board 07)."""
        with self._lock:
            self._atomic_write_json(self.history_path, get_default_history_payload())

