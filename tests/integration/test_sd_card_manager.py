"""Integration and unit tests for SDCardManager (TC-008, TC-009, TC-010, TC-019, TC-028)."""

import os
from pathlib import Path
from typing import Optional
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.fs]

from pladaz.domain.errors import (
    ErrorCode,
    SDCardDisconnectedError,
    SDCardInsufficientSpaceError,
    SDCardVerifyFailedError,
)
from pladaz.domain.interfaces import DriveProbeProtocol
from pladaz.domain.models import SDCardStatus
from pladaz.services.sd_card_manager import (
    OVERWRITE_TEMP_SUFFIX,
    SDCardManager,
)


class FakeDriveProbe(DriveProbeProtocol):
    """Controllable DriveProbeProtocol for simulating SD Card states and mid-copy disconnects."""

    def __init__(
        self,
        root_dir: Path,
        is_connected: bool = True,
        is_writable: bool = True,
        free_bytes: int = 100 * 1024 * 1024,
        total_bytes: int = 1024 * 1024 * 1024,
        volume_label: Optional[str] = "SNOWSKY_SD",
        fail_mid_copy: bool = False,
        corrupt_copy_bytes: bool = False,
    ) -> None:
        self.root_dir = root_dir
        self.is_connected = is_connected
        self.is_writable = is_writable
        self.free_bytes = free_bytes
        self.total_bytes = total_bytes
        self.volume_label = volume_label
        self.fail_mid_copy = fail_mid_copy
        self.corrupt_copy_bytes = corrupt_copy_bytes

    def list_removable_drives(self) -> list[SDCardStatus]:
        if not self.is_connected:
            return []
        return [
            SDCardStatus(
                drive_root=str(self.root_dir),
                destination_dir=str(self.root_dir),
                is_connected=self.is_connected,
                is_writable=self.is_writable,
                free_bytes=self.free_bytes,
                total_bytes=self.total_bytes,
                volume_label=self.volume_label,
            )
        ]

    def probe_destination(self, dest: Path) -> SDCardStatus:
        return SDCardStatus(
            drive_root=str(self.root_dir),
            destination_dir=str(dest),
            is_connected=self.is_connected,
            is_writable=self.is_writable,
            free_bytes=self.free_bytes,
            total_bytes=self.total_bytes,
            volume_label=self.volume_label,
        )

    def copy_file_with_fsync(self, src: Path, dst: Path) -> None:
        data = src.read_bytes()
        if self.fail_mid_copy:
            # Write partial (half) file to disk then simulate card disconnect OSError
            dst.write_bytes(data[: max(1, len(data) // 2)])
            self.is_connected = False
            raise OSError("Simulated SD Card removal mid-copy")

        if self.corrupt_copy_bytes:
            # Write truncated bytes without raising OSError so Verify catches size mismatch
            dst.write_bytes(data[:-10])
            return

        with open(dst, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())


def test_tc008_select_accessible_destination_and_copy_verify(
    tmp_path: Path,
    sample_m4a_path: Path,
) -> None:
    """TC-008: User selects an accessible destination folder on SD Card; system checks and writes to it."""
    sd_root = tmp_path / "sdcard"
    sd_root.mkdir()
    probe = FakeDriveProbe(root_dir=sd_root)
    manager = SDCardManager(drive_probe=probe)

    drives = manager.list_removable_drives()
    assert len(drives) == 1
    assert drives[0].volume_label == "SNOWSKY_SD"

    dest_folder = sd_root / "Music"
    status = manager.check_destination(dest_folder, required_bytes=1024)
    assert status.is_connected is True
    assert status.is_writable is True

    target_file = dest_folder / "Artist" / "Album" / "Song.m4a"
    final_path = manager.copy_and_verify(sample_m4a_path, target_file, overwrite=False)
    assert final_path == target_file
    assert final_path.exists()
    assert final_path.stat().st_size == sample_m4a_path.stat().st_size

    manager.cleanup_temp(sample_m4a_path)
    assert not sample_m4a_path.exists()


def test_tc009_destination_disconnected_or_read_only_raises_error(
    tmp_path: Path,
) -> None:
    """TC-009: When storage device is disconnected or read-only, system raises clear SDCardDisconnectedError."""
    sd_root = tmp_path / "sdcard"
    probe_disconnected = FakeDriveProbe(root_dir=sd_root, is_connected=False)
    manager_disc = SDCardManager(drive_probe=probe_disconnected)

    with pytest.raises(SDCardDisconnectedError) as exc_info:
        manager_disc.check_destination(sd_root / "Music", required_bytes=100)
    assert exc_info.value.code == ErrorCode.ERR_SDCARD_DISCONNECTED

    probe_ro = FakeDriveProbe(root_dir=sd_root, is_connected=True, is_writable=False)
    manager_ro = SDCardManager(drive_probe=probe_ro)

    with pytest.raises(SDCardDisconnectedError) as exc_info_ro:
        manager_ro.check_destination(sd_root / "Music", required_bytes=100)
    assert exc_info_ro.value.code == ErrorCode.ERR_SDCARD_DISCONNECTED
    assert "read-only" in exc_info_ro.value.message_en.lower()


def test_tc010_insufficient_free_space_raises_error(
    tmp_path: Path,
    sample_m4a_path: Path,
) -> None:
    """TC-010: When destination has insufficient free space, system raises SDCardInsufficientSpaceError."""
    sd_root = tmp_path / "sdcard"
    sd_root.mkdir()
    probe = FakeDriveProbe(root_dir=sd_root, free_bytes=100)  # Only 100 bytes free
    manager = SDCardManager(drive_probe=probe)

    target_file = sd_root / "Artist" / "Album" / "Song.m4a"
    with pytest.raises(SDCardInsufficientSpaceError) as exc_info:
        manager.copy_and_verify(sample_m4a_path, target_file)

    assert exc_info.value.code == ErrorCode.ERR_SDCARD_INSUFFICIENT_SPACE
    assert not target_file.exists()


def test_tc019_card_disconnected_mid_copy_cleans_up_partial_file_and_detects_disconnect(
    tmp_path: Path,
    sample_m4a_path: Path,
) -> None:
    """TC-019 (DEC-041): Card removed during copy raises ERR_SDCARD_DISCONNECTED, deletes partial file, and is_card_present returns False."""
    sd_root = tmp_path / "sdcard"
    sd_root.mkdir()
    probe = FakeDriveProbe(root_dir=sd_root, fail_mid_copy=True)
    manager = SDCardManager(drive_probe=probe)

    assert manager.is_card_present(sd_root) is True

    target_file = sd_root / "Artist" / "Album" / "Track.m4a"
    with pytest.raises(SDCardDisconnectedError) as exc_info:
        manager.copy_and_verify(sample_m4a_path, target_file, overwrite=False)

    assert exc_info.value.code == ErrorCode.ERR_SDCARD_DISCONNECTED
    # Partial file must be cleaned up
    assert not target_file.exists()
    # Periodic check now sees card is disconnected
    assert manager.is_card_present(sd_root) is False


def test_tc028_overwrite_card_disconnected_mid_copy_preserves_original_file(
    tmp_path: Path,
    sample_m4a_path: Path,
) -> None:
    """TC-028 (DEC-040): When overwriting an existing file and the card disconnects mid-copy, the original file on the card remains intact."""
    sd_root = tmp_path / "sdcard"
    album_dir = sd_root / "Artist" / "Album"
    album_dir.mkdir(parents=True)

    existing_target = album_dir / "ExistingSong.m4a"
    original_bytes = b"ORIGINAL_INTACT_M4A_CONTENT_DO_NOT_LOSE"
    existing_target.write_bytes(original_bytes)

    probe = FakeDriveProbe(root_dir=sd_root, fail_mid_copy=True)
    manager = SDCardManager(drive_probe=probe)

    with pytest.raises(SDCardDisconnectedError) as exc_info:
        manager.copy_and_verify(sample_m4a_path, existing_target, overwrite=True)

    assert exc_info.value.code == ErrorCode.ERR_SDCARD_DISCONNECTED
    # Original file must still exist and have its exact original bytes!
    assert existing_target.exists()
    assert existing_target.read_bytes() == original_bytes
    # Temporary .pladaz-tmp file must be removed
    temp_on_card = existing_target.with_name(
        f"{existing_target.name}{OVERWRITE_TEMP_SUFFIX}"
    )
    assert not temp_on_card.exists()


def test_verify_catches_size_mismatch_and_cleans_up(
    tmp_path: Path,
    sample_m4a_path: Path,
) -> None:
    """Verify step raises ERR_SDCARD_VERIFY_FAILED when copied file size does not match source."""
    sd_root = tmp_path / "sdcard"
    sd_root.mkdir()
    probe = FakeDriveProbe(root_dir=sd_root, corrupt_copy_bytes=True)
    manager = SDCardManager(drive_probe=probe)

    target_file = sd_root / "Artist" / "Album" / "CorruptedCopy.m4a"
    with pytest.raises(SDCardVerifyFailedError) as exc_info:
        manager.copy_and_verify(sample_m4a_path, target_file, overwrite=False)

    assert exc_info.value.code == ErrorCode.ERR_SDCARD_VERIFY_FAILED
    assert not target_file.exists()

