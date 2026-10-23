"""AudioProcessingService wrapping FFmpeg for AAC-LC M4A remuxing and encoding (SYSTEM_DESIGN.md 2.5(4), IR-004, DEC-033, TBA-027, TC-024)."""

import os
from pathlib import Path
import shutil
import subprocess
from threading import Event
import time
from typing import Optional

from pladaz.domain.enums import AudioProcessMode
from pladaz.domain.errors import (
    AudioProcessingError,
    ErrorCode,
    TaskCancelledError,
)
from pladaz.services.logger import PladazLogger, redact_sensitive_text

DEFAULT_FFMPEG_TIMEOUT_SEC: float = 300.0


def _subprocess_creation_flags() -> int:
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return 0


def resolve_ffmpeg_binary(explicit_path: Optional[Path] = None) -> str:
    """Resolve path to ffmpeg executable (explicit path -> bin/ffmpeg.exe -> system PATH)."""
    if explicit_path is not None and Path(explicit_path).exists():
        return str(Path(explicit_path))
    bundled = Path("bin") / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)
    which_ffmpeg = shutil.which("ffmpeg")
    if which_ffmpeg:
        return which_ffmpeg
    return "ffmpeg"


class AudioProcessingService:
    """Processes downloaded audio streams into M4A (AAC-LC) containers using FFmpeg."""

    def __init__(
        self,
        ffmpeg_path: Optional[Path] = None,
        logger: Optional[PladazLogger] = None,
        timeout_sec: float = DEFAULT_FFMPEG_TIMEOUT_SEC,
        # TBA-027: Fallback encode bitrate remains TBA; default is None (do NOT pass -b:a to FFmpeg)
        fallback_bitrate: Optional[str] = None,
    ) -> None:
        self._explicit_ffmpeg_path = ffmpeg_path
        self._logger = logger
        self.timeout_sec = timeout_sec
        self.fallback_bitrate = fallback_bitrate

    def build_ffmpeg_args(
        self,
        input_path: Path,
        output_path: Path,
        mode: AudioProcessMode,
    ) -> list[str]:
        """Construct the exact FFmpeg command-line argument list for REMUX_AAC or ENCODE_AAC_LC (DEC-033, TBA-027)."""
        ffmpeg_bin = resolve_ffmpeg_binary(self._explicit_ffmpeg_path)
        cmd: list[str] = [
            ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-vn",
        ]
        if mode == AudioProcessMode.REMUX_AAC:
            cmd.extend(["-c:a", "copy"])
        elif mode == AudioProcessMode.ENCODE_AAC_LC:
            cmd.extend(["-c:a", "aac", "-profile:a", "aac_low"])
            # TBA-027: Only append -b:a if explicitly configured; keep omitted by default
            if self.fallback_bitrate:
                cmd.extend(["-b:a", self.fallback_bitrate])
        else:
            raise ValueError(f"Unsupported AudioProcessMode: {mode}")

        cmd.extend(["-movflags", "+faststart", str(output_path)])
        return cmd

    def to_m4a(
        self,
        input_path: Path,
        output_path: Path,
        mode: AudioProcessMode,
        cancel_event: Optional[Event] = None,
    ) -> Path:
        """Convert or remux `input_path` to `output_path` (.m4a) using FFmpeg (DEC-033, TC-024)."""
        src = Path(input_path)
        dst = Path(output_path)

        if cancel_event is not None and cancel_event.is_set():
            raise TaskCancelledError()

        if not src.exists():
            raise AudioProcessingError(
                message_en=f"Input audio file for FFmpeg does not exist: '{src.name}'.",
                details=f"missing_input={src}",
            )

        dst.parent.mkdir(parents=True, exist_ok=True)
        cmd = self.build_ffmpeg_args(src, dst, mode)

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                creationflags=_subprocess_creation_flags(),
            )
        except OSError as exc:
            err_msg = f"Failed to launch FFmpeg: {exc}"
            if self._logger:
                self._logger.error(
                    component="AudioProcessingService",
                    message=err_msg,
                    error_code=ErrorCode.ERR_AUDIO_FFMPEG_FAILED,
                )
            raise AudioProcessingError(
                message_en="Failed to launch FFmpeg executable.",
                details=redact_sensitive_text(str(exc)),
            ) from exc

        start_time = time.monotonic()
        try:
            while proc.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    dst.unlink(missing_ok=True)
                    raise TaskCancelledError()

                if (time.monotonic() - start_time) > self.timeout_sec:
                    proc.kill()
                    dst.unlink(missing_ok=True)
                    raise AudioProcessingError(
                        message_en="FFmpeg audio processing timed out.",
                        details=f"timeout={self.timeout_sec}s",
                    )
                time.sleep(0.02)

            _, stderr_text = proc.communicate(timeout=5)
        except TaskCancelledError:
            raise
        except AudioProcessingError:
            raise
        except Exception as exc:
            proc.kill()
            dst.unlink(missing_ok=True)
            raise AudioProcessingError(
                message_en="FFmpeg encountered an unexpected error.",
                details=redact_sensitive_text(str(exc)),
            ) from exc

        if proc.returncode != 0 or not dst.exists() or dst.stat().st_size <= 0:
            dst.unlink(missing_ok=True)
            safe_stderr = redact_sensitive_text((stderr_text or "").strip())
            if self._logger:
                self._logger.error(
                    component="AudioProcessingService",
                    message=f"FFmpeg failed (code={proc.returncode}): {safe_stderr}",
                    error_code=ErrorCode.ERR_AUDIO_FFMPEG_FAILED,
                )
            raise AudioProcessingError(
                message_en=f"FFmpeg failed to process audio stream ({mode.value}).",
                details=safe_stderr or f"exit_code={proc.returncode}",
            )

        return dst

