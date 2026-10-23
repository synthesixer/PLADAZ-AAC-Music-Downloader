"""SDCardManager service and WindowsDriveProbe (SYSTEM_DESIGN.md 2.5(6), IR-008, IR-019, DEC-032, DEC-040, DEC-041)."""

import ctypes
import os
from pathlib import Path
from typing import Optional

from mutagen.mp4 import MP4
import psutil

from pladaz.domain.errors import (
    SDCardDisconnectedError,
    SDCardInsufficientSpaceError,
    SDCardVerifyFailedError,
)
from pladaz.domain.interfaces import DriveProbeProtocol
from pladaz.domain.models import SDCardStatus
from pladaz.services.logger import PladazLogger

# Windows GetDriveTypeW return code for removable media (SD Card / USB Flash Drive)
DRIVE_REMOVABLE: int = 2

# Copy buffer size (64 KB)
COPY_CHUNK_SIZE: int = 64 * 1024

# Suffix for temporary staging file on the SD card during Overwrite (DEC-040 [Proposal])
OVERWRITE_TEMP_SUFFIX: str = ".pladaz-tmp"


def _get_windows_volume_label(drive_root: str) -> Optional[str]:
    """Query the Windows volume label using GetVolumeInformationW."""
    if os.name != "nt":
        return None
    try:
        kernel32 = ctypes.windll.kernel32
        vol_name_buf = ctypes.create_unicode_buffer(261)
        fs_name_buf = ctypes.create_unicode_buffer(261)
        serial_num = ctypes.c_ulong(0)
        max_comp_len = ctypes.c_ulong(0)
        fs_flags = ctypes.c_ulong(0)
        res = kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(drive_root),
            vol_name_buf,
            ctypes.sizeof(vol_name_buf),
            ctypes.byref(serial_num),
            ctypes.byref(max_comp_len),
            ctypes.byref(fs_flags),
            fs_name_buf,
            ctypes.sizeof(fs_name_buf),
        )
        if res:
            return vol_name_buf.value or None
    except Exception:
        pass
    return None


def _get_windows_drive_type(drive_root: str) -> int:
    """Query Windows GetDriveTypeW for a drive root like 'E:\\'."""
    if os.name != "nt":
        return 0
    try:
        return int(ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(drive_root)))
    except Exception:
        return 0


class WindowsDriveProbe(DriveProbeProtocol):
    """Production implementation of DriveProbeProtocol using psutil and Win32 API."""

    def list_removable_drives(self) -> list[SDCardStatus]:
        drives: list[SDCardStatus] = []
        for part in psutil.disk_partitions(all=False):
            mountpoint = part.mountpoint
            drive_type = _get_windows_drive_type(mountpoint)
            if drive_type != DRIVE_REMOVABLE:
                continue
            try:
                usage = psutil.disk_usage(mountpoint)
                is_writable = "ro" not in (part.opts or "").lower()
                drives.append(
                    SDCardStatus(
                        drive_root=mountpoint,
                        destination_dir=mountpoint,
                        is_connected=True,
                        is_writable=is_writable,
                        free_bytes=int(usage.free),
                        total_bytes=int(usage.total),
                        volume_label=_get_windows_volume_label(mountpoint),
                    )
                )
            except OSError:
                continue
        return drives

    def probe_destination(self, dest: Path) -> SDCardStatus:
        dest_path = Path(dest).resolve()
        drive_root = dest_path.anchor or str(dest_path)
        if not Path(drive_root).exists():
            return SDCardStatus(
                drive_root=drive_root,
                destination_dir=str(dest_path),
                is_connected=False,
                is_writable=False,
                free_bytes=0,
                total_bytes=0,
                volume_label=None,
            )

        # Find closest existing ancestor to query disk usage
        probe_target = dest_path
        while not probe_target.exists() and probe_target.parent != probe_target:
            probe_target = probe_target.parent

        if not probe_target.exists():
            return SDCardStatus(
                drive_root=drive_root,
                destination_dir=str(dest_path),
                is_connected=False,
                is_writable=False,
                free_bytes=0,
                total_bytes=0,
                volume_label=None,
            )

        try:
            usage = psutil.disk_usage(str(probe_target))
            is_writable = os.access(str(probe_target), os.W_OK)
            return SDCardStatus(
                drive_root=drive_root,
                destination_dir=str(dest_path),
                is_connected=True,
                is_writable=is_writable,
                free_bytes=int(usage.free),
                total_bytes=int(usage.total),
                volume_label=_get_windows_volume_label(drive_root),
            )
        except OSError:
            return SDCardStatus(
                drive_root=drive_root,
                destination_dir=str(dest_path),
                is_connected=False,
                is_writable=False,
                free_bytes=0,
                total_bytes=0,
                volume_label=None,
            )

    def copy_file_with_fsync(self, src: Path, dst: Path) -> None:
        """Read from src and write to dst in chunks, flushing and calling os.fsync() before closing."""
        with open(src, "rb") as f_src, open(dst, "wb") as f_dst:
            while True:
                chunk = f_src.read(COPY_CHUNK_SIZE)
                if not chunk:
                    break
                f_dst.write(chunk)
            f_dst.flush()
            os.fsync(f_dst.fileno())


class SDCardManager:
    """Manages Micro SD Card detection, space checks, Copy & Verify, and safe Overwrite (DEC-032, DEC-040)."""

    def __init__(
        self,
        drive_probe: Optional[DriveProbeProtocol] = None,
        logger: Optional[PladazLogger] = None,
    ) -> None:
        self._probe: DriveProbeProtocol = drive_probe or WindowsDriveProbe()
        self._logger = logger

    def list_removable_drives(self) -> list[SDCardStatus]:
        """Return list of currently connected removable drives."""
        return self._probe.list_removable_drives()

    def is_card_present(self, dest: Path) -> bool:
        """Fast check used for periodic card monitoring during download/processing (DEC-041)."""
        status = self._probe.probe_destination(Path(dest))
        return bool(status.is_connected and status.is_writable)

    def cleanup_stale_overwrite_temps(self, folder: Path) -> None:
        """Remove any leftover *.pladaz-tmp files in `folder` from a previous interrupted overwrite (SYSTEM_DESIGN.md 2.5(6))."""
        try:
            folder_path = Path(folder)
            if folder_path.exists() and folder_path.is_dir():
                for stale in folder_path.glob(f"*{OVERWRITE_TEMP_SUFFIX}"):
                    try:
                        stale.unlink(missing_ok=True)
                    except OSError:
                        pass
        except OSError:
            pass

    def check_destination(
        self,
        dest: Path,
        required_bytes: int = 0,
    ) -> SDCardStatus:
        """Verify that destination drive is connected, writable, and has at least `required_bytes` free."""
        dest_path = Path(dest)
        status = self._probe.probe_destination(dest_path)

        if not status.is_connected:
            raise SDCardDisconnectedError(
                message_en=f"Destination drive '{status.drive_root}' is disconnected or inaccessible.",
                details=f"dest={dest_path}",
            )

        if not status.is_writable:
            raise SDCardDisconnectedError(
                message_en=f"Destination '{dest_path}' is read-only or not writable.",
                details=f"dest={dest_path}, writable=False",
            )

        if required_bytes > 0 and status.free_bytes < required_bytes:
            raise SDCardInsufficientSpaceError(
                message_en=(
                    f"Insufficient space on Micro SD Card: required {required_bytes} bytes, "
                    f"available {status.free_bytes} bytes."
                ),
                details=f"required={required_bytes}, free={status.free_bytes}",
            )

        self.cleanup_stale_overwrite_temps(dest_path)
        return status

    def copy_and_verify(
        self,
        temp_file: Path,
        target: Path,
        overwrite: bool = False,
    ) -> Path:
        """Copy `temp_file` to `target` on SD Card with fsync and verify size + mutagen readability (DEC-032, DEC-040).

        - When `overwrite=True` (or overwriting an existing file), copies first to `<Title>.m4a.pladaz-tmp`
          in the same target folder, verifies it, and then replaces `target` via `os.replace()` so the
          existing file on the card is preserved if the card disconnects mid-copy (DEC-040, TC-028).
        """
        src_path = Path(temp_file)
        target_path = Path(target)

        if not src_path.exists():
            raise FileNotFoundError(f"Source temp file does not exist: {src_path}")

        expected_size = src_path.stat().st_size
        if expected_size <= 0:
            raise SDCardVerifyFailedError(
                message_en="Source temp file is empty (0 bytes).",
                details=f"src={src_path}",
            )

        # 1. Check card connectivity and free space
        self.check_destination(target_path.parent, required_bytes=expected_size)

        # 2. Ensure target directory exists and clean up any leftover .pladaz-tmp files
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            self.cleanup_stale_overwrite_temps(target_path.parent)
        except OSError as exc:
            raise SDCardDisconnectedError(
                message_en="Failed to create destination folder on Micro SD Card (card may have been removed).",
                details=str(exc),
            ) from exc

        use_staged_overwrite = overwrite or target_path.exists()
        write_path = (
            target_path.with_name(f"{target_path.name}{OVERWRITE_TEMP_SUFFIX}")
            if use_staged_overwrite
            else target_path
        )

        # 3. Copy with flush() + os.fsync()
        try:
            self._probe.copy_file_with_fsync(src_path, write_path)
        except OSError as exc:
            self._safe_unlink(write_path)
            raise SDCardDisconnectedError(
                message_en="Micro SD Card was disconnected or encountered an I/O error during file copy.",
                details=str(exc),
            ) from exc

        # 4. Verify copied file on card (existence, exact byte size, and mutagen MP4 container readability)
        try:
            if not write_path.exists():
                raise SDCardVerifyFailedError(
                    message_en="Copied file was not found on Micro SD Card during verification.",
                    details=f"write_path={write_path}",
                )
            actual_size = write_path.stat().st_size
            if actual_size != expected_size:
                raise SDCardVerifyFailedError(
                    message_en=(
                        f"File size mismatch on Micro SD Card: expected {expected_size} bytes, "
                        f"got {actual_size} bytes."
                    ),
                    details=f"expected={expected_size}, actual={actual_size}",
                )
            mp4 = MP4(write_path)
            if mp4.info is None or getattr(mp4.info, "length", 0) <= 0:
                raise SDCardVerifyFailedError(
                    message_en="Copied M4A file on Micro SD Card has invalid audio stream info.",
                )
        except SDCardVerifyFailedError:
            self._safe_unlink(write_path)
            raise
        except OSError as exc:
            self._safe_unlink(write_path)
            raise SDCardDisconnectedError(
                message_en="Micro SD Card disconnected during file verification.",
                details=str(exc),
            ) from exc
        except Exception as exc:
            self._safe_unlink(write_path)
            raise SDCardVerifyFailedError(
                message_en="Copied M4A container on Micro SD Card could not be read by mutagen.",
                details=str(exc),
            ) from exc

        # 5. If staged overwrite was used, atomically replace the target file on the same drive (DEC-040)
        if write_path != target_path:
            try:
                os.replace(write_path, target_path)
            except OSError as exc:
                self._safe_unlink(write_path)
                raise SDCardDisconnectedError(
                    message_en="Failed to replace existing file on Micro SD Card (card may have been removed).",
                    details=str(exc),
                ) from exc

        return target_path

    def cleanup_temp(self, path: Path) -> None:
        """Delete the temporary staging file in Temp after successful copy or failure."""
        self._safe_unlink(Path(path))

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

