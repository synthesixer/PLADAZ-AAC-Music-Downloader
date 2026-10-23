"""Unit tests for ConfigHistoryStore (TC-029 config persistence part, TC-030)."""

from pathlib import Path

from pladaz.domain.enums import TaskStatus
from pladaz.domain.errors import ErrorCode
from pladaz.domain.models import HistoryEntry
from pladaz.services.config_store import (
    CONFIG_KEY_REQUIRE_ALBUM_ART,
    ConfigHistoryStore,
)
from pladaz.services.logger import PladazLogger


def test_tc029_disclaimer_accepted_persisted_in_config(tmp_path: Path) -> None:
    """TC-029 (Backend store part): First load has disclaimer_accepted=False; saving True persists across reloads."""
    store = ConfigHistoryStore(base_dir=tmp_path)

    initial_cfg = store.load_config()
    assert initial_cfg["disclaimer_accepted"] is False
    assert initial_cfg[CONFIG_KEY_REQUIRE_ALBUM_ART] is False

    initial_cfg["disclaimer_accepted"] = True
    store.save_config(initial_cfg)

    reloaded_store = ConfigHistoryStore(base_dir=tmp_path)
    reloaded_cfg = reloaded_store.load_config()
    assert reloaded_cfg["disclaimer_accepted"] is True


def test_tc030a_config_and_history_normal_read_write(tmp_path: Path) -> None:
    """TC-030(a): Normal read and write for config.json and history.json."""
    store = ConfigHistoryStore(base_dir=tmp_path)

    cfg = store.load_config()
    cfg["destination_path"] = "E:\\Music"
    cfg[CONFIG_KEY_REQUIRE_ALBUM_ART] = True
    store.save_config(cfg)

    loaded_cfg = store.load_config()
    assert loaded_cfg["destination_path"] == "E:\\Music"
    assert loaded_cfg[CONFIG_KEY_REQUIRE_ALBUM_ART] is True
    assert loaded_cfg["schema_version"] == 1

    entry1 = HistoryEntry(
        task_id="task-001",
        finished_at="2026-10-23T18:00:00Z",
        status=TaskStatus.COMPLETED,
        title="Test Song",
        album_artist="Test Album Artist",
        album="Test Album",
        target_file_path="E:\\Music\\Test Album Artist\\Test Album\\Test Song.m4a",
        source_url="https://music.youtube.com/watch?v=12345",
        warnings=[],
        error_code=None,
    )
    entry2 = HistoryEntry(
        task_id="task-002",
        finished_at="2026-10-23T18:05:00Z",
        status=TaskStatus.FAILED,
        title="Broken Song",
        album_artist=None,
        album=None,
        target_file_path=None,
        source_url="https://www.youtube.com/watch?v=67890",
        warnings=["Enrichment timed out"],
        error_code=ErrorCode.ERR_SOURCE_NETWORK_TIMEOUT,
    )
    store.append_history(entry1)
    store.append_history(entry2)

    entries = store.load_history()
    assert len(entries) == 2
    assert entries[0].task_id == "task-001"
    assert entries[0].status == TaskStatus.COMPLETED
    assert entries[1].task_id == "task-002"
    assert entries[1].status == TaskStatus.FAILED
    assert entries[1].error_code == ErrorCode.ERR_SOURCE_NETWORK_TIMEOUT


def test_tc030b_corrupted_config_and_history_recovery(tmp_path: Path) -> None:
    """TC-030(b): Corrupted config.json and history.json are backed up as *.corrupt-* and reset to defaults without crashing."""
    logger = PladazLogger(log_dir=tmp_path / "logs")
    try:
        store = ConfigHistoryStore(base_dir=tmp_path, logger=logger)

        # Write broken JSON to config.json
        (tmp_path / "config.json").write_text("{broken_json: true,", encoding="utf-8")

        recovered_cfg = store.load_config()
        assert recovered_cfg["disclaimer_accepted"] is False
        assert recovered_cfg["destination_path"] == ""
        assert store.last_error is not None
        assert store.last_error.code == ErrorCode.ERR_CONFIG_CORRUPT

        corrupt_backups = list(tmp_path.glob("config.json.corrupt-*"))
        assert len(corrupt_backups) == 1
        assert corrupt_backups[0].read_text(encoding="utf-8") == "{broken_json: true,"

        # Write invalid structure to history.json
        store.last_error = None
        (tmp_path / "history.json").write_text('{"entries": "not-a-list"}', encoding="utf-8")

        recovered_history = store.load_history()
        assert recovered_history == []
        assert store.last_error is not None
        assert store.last_error.code == ErrorCode.ERR_CONFIG_CORRUPT

        history_backups = list(tmp_path.glob("history.json.corrupt-*"))
        assert len(history_backups) == 1
    finally:
        logger.close()

