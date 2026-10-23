"""DownloadSourceAdapter service wrapping standalone yt-dlp.exe (SYSTEM_DESIGN.md 2.5(1), DEC-033, DEC-038, TC-024, TC-031)."""

import json
import os
from pathlib import Path
import subprocess
from threading import Event
import time
from typing import Any, Callable, Optional
from urllib.parse import urlparse
import urllib.request
import uuid

from pladaz.domain.enums import AudioProcessMode
from pladaz.domain.errors import (
    ErrorCode,
    SourceExtractionError,
    SourceInvalidUrlError,
    SourceNetworkTimeoutError,
    TaskCancelledError,
)
from pladaz.domain.models import (
    AudioFormat,
    RawSourceEntry,
    RawTrackInfo,
    StreamPlan,
    UpdateResult,
)
from pladaz.services.logger import PladazLogger, redact_sensitive_text

# Official GitHub Release URL for standalone Windows yt-dlp.exe (confirmed by user for DEC-038)
YTDLP_LATEST_RELEASE_URL: str = (
    "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
)

# Allowed YouTube / YouTube Music hostnames (IR-007)
ALLOWED_YOUTUBE_HOSTS: frozenset[str] = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
    }
)

DEFAULT_SUBPROCESS_TIMEOUT_SEC: float = 120.0
DEFAULT_DOWNLOAD_TIMEOUT_SEC: float = 600.0

ProgressCallback = Callable[[float, str, str], None]
BinaryDownloader = Callable[[str, Path], None]


def _subprocess_creation_flags() -> int:
    """Return CREATE_NO_WINDOW on Windows so subprocesses never flash a console window."""
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return 0


def validate_youtube_url(url: str) -> str:
    """Validate that `url` is a syntactically valid YouTube or YouTube Music HTTP(S) URL (IR-007).

    Raises SourceInvalidUrlError (ERR_SOURCE_INVALID_URL) if invalid.
    """
    if not url or not isinstance(url, str) or not url.strip():
        raise SourceInvalidUrlError(
            message_en="URL cannot be empty. Please provide a valid YouTube or YouTube Music URL."
        )
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https"):
        raise SourceInvalidUrlError(
            message_en="Invalid URL scheme. Only http:// and https:// YouTube links are supported.",
            details=f"scheme={parsed.scheme!r}",
        )
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_YOUTUBE_HOSTS:
        raise SourceInvalidUrlError(
            message_en=f"Unsupported domain '{host}'. Only YouTube and YouTube Music links are supported.",
            details=f"host={host!r}",
        )
    path_and_query = (parsed.path or "").strip("/") + (parsed.query or "")
    if not path_and_query:
        raise SourceInvalidUrlError(
            message_en="URL is missing a video, playlist, or album identifier.",
            details=f"url={cleaned!r}",
        )
    return cleaned


def _safe_int(val: Any) -> Optional[int]:
    if val is None or isinstance(val, bool):
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _safe_float(val: Any) -> Optional[float]:
    if val is None or isinstance(val, bool):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _extract_year(data: dict[str, Any]) -> Optional[str]:
    release_year = data.get("release_year")
    if release_year is not None:
        year_str = str(release_year).strip()
        if year_str:
            return year_str
    for date_key in ("release_date", "upload_date"):
        raw_date = data.get(date_key)
        if isinstance(raw_date, str) and len(raw_date.strip()) >= 4:
            prefix = raw_date.strip()[:4]
            if prefix.isdigit():
                return prefix
    return None


def parse_flat_entries(
    data: dict[str, Any],
    original_url: str,
    batch_id: Optional[str] = None,
) -> list[RawSourceEntry]:
    """Parse yt-dlp `--flat-playlist --dump-single-json` output into RawSourceEntry items."""
    resolved_batch_id = batch_id or str(uuid.uuid4())

    if data.get("_type") in ("playlist", "multi_video") or isinstance(
        data.get("entries"), list
    ):
        raw_entries = data.get("entries") or []
        results: list[RawSourceEntry] = []
        for idx, item in enumerate(raw_entries):
            if not isinstance(item, dict):
                continue
            entry_url = item.get("url") or item.get("webpage_url")
            video_id = item.get("id")
            if not entry_url and video_id:
                entry_url = f"https://www.youtube.com/watch?v={video_id}"
            elif (
                isinstance(entry_url, str)
                and not entry_url.startswith("http")
                and video_id
            ):
                entry_url = f"https://www.youtube.com/watch?v={video_id}"
            if not entry_url:
                continue
            title_hint = item.get("title") or item.get("track")
            results.append(
                RawSourceEntry(
                    entry_url=str(entry_url),
                    title_hint=str(title_hint).strip() if title_hint else None,
                    batch_id=resolved_batch_id,
                    index_in_batch=idx,
                )
            )
        if not results:
            raise SourceExtractionError(
                message_en="No playable tracks were found in the playlist or album.",
            )
        return results

    # Single track response
    single_url = data.get("webpage_url") or data.get("original_url") or original_url
    title_hint = data.get("track") or data.get("title")
    return [
        RawSourceEntry(
            entry_url=str(single_url),
            title_hint=str(title_hint).strip() if title_hint else None,
            batch_id=resolved_batch_id,
            index_in_batch=0,
        )
    ]


def parse_track_info(data: dict[str, Any], entry_url: str) -> RawTrackInfo:
    """Parse full yt-dlp `--dump-single-json --no-playlist` output into RawTrackInfo."""
    title = data.get("track") or data.get("title")
    artist = (
        data.get("artist")
        or data.get("creator")
        or data.get("uploader")
        or data.get("channel")
    )
    album = data.get("album")
    album_artist = data.get("album_artist")
    track_number = _safe_int(data.get("track_number"))
    disc_number = _safe_int(data.get("disc_number"))
    release_year = _extract_year(data)
    genre = data.get("genre")
    thumbnail_url = data.get("thumbnail")
    if not thumbnail_url:
        thumbnails = data.get("thumbnails")
        if isinstance(thumbnails, list) and thumbnails:
            for thumb in reversed(thumbnails):
                if isinstance(thumb, dict) and thumb.get("url"):
                    thumbnail_url = thumb["url"]
                    break

    audio_formats: list[AudioFormat] = []
    for fmt in data.get("formats") or []:
        if not isinstance(fmt, dict):
            continue
        format_id = fmt.get("format_id")
        acodec = fmt.get("acodec")
        ext = fmt.get("ext")
        if not format_id or not acodec or str(acodec).lower() == "none":
            continue
        audio_formats.append(
            AudioFormat(
                format_id=str(format_id),
                acodec=str(acodec),
                abr=_safe_float(fmt.get("abr") or fmt.get("tbr")),
                ext=str(ext or ""),
            )
        )

    return RawTrackInfo(
        entry_url=entry_url,
        title=str(title).strip() if title else None,
        artist=str(artist).strip() if artist else None,
        album=str(album).strip() if album else None,
        album_artist=str(album_artist).strip() if album_artist else None,
        track_number=track_number,
        disc_number=disc_number,
        release_year=release_year,
        genre=str(genre).strip() if genre else None,
        thumbnail_url=str(thumbnail_url).strip() if thumbnail_url else None,
        audio_formats=audio_formats,
    )


def _default_binary_downloader(url: str, dest_path: Path) -> None:
    """Download binary from `url` to `dest_path` using urllib.request."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "PLADAZ-Updater/1.0"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest_path, "wb") as out:
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            out.write(chunk)
        out.flush()
        os.fsync(out.fileno())


class DownloadSourceAdapter:
    """Adapter around standalone yt-dlp.exe for link extraction, stream planning, downloading, and updating."""

    def __init__(
        self,
        ytdlp_path: Path,
        logger: Optional[PladazLogger] = None,
        subprocess_timeout_sec: float = DEFAULT_SUBPROCESS_TIMEOUT_SEC,
        download_timeout_sec: float = DEFAULT_DOWNLOAD_TIMEOUT_SEC,
        update_url: str = YTDLP_LATEST_RELEASE_URL,
        binary_downloader: Optional[BinaryDownloader] = None,
    ) -> None:
        self.ytdlp_path = Path(ytdlp_path)
        self._logger = logger
        self.subprocess_timeout_sec = subprocess_timeout_sec
        self.download_timeout_sec = download_timeout_sec
        self.update_url = update_url
        self._binary_downloader: BinaryDownloader = (
            binary_downloader or _default_binary_downloader
        )

    def _build_base_cmd(self, cookies_path: Optional[Path] = None) -> list[str]:
        if not self.ytdlp_path.exists():
            raise SourceExtractionError(
                message_en=f"yt-dlp executable was not found at '{self.ytdlp_path}'.",
                details=f"missing_binary={self.ytdlp_path}",
            )
        cmd: list[str] = [
            str(self.ytdlp_path),
            "--no-warnings",
            "--encoding",
            "utf-8",
        ]
        if cookies_path is not None:
            cookies_file = Path(cookies_path)
            if cookies_file.exists():
                cmd.extend(["--cookies", str(cookies_file)])
        return cmd

    def _run_json_command(
        self,
        args: list[str],
        cookies_path: Optional[Path] = None,
    ) -> dict[str, Any]:
        cmd = self._build_base_cmd(cookies_path=cookies_path) + args
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.subprocess_timeout_sec,
                shell=False,
                creationflags=_subprocess_creation_flags(),
            )
        except subprocess.TimeoutExpired as exc:
            raise SourceNetworkTimeoutError(
                message_en="Timed out while waiting for yt-dlp response.",
                details=f"timeout={self.subprocess_timeout_sec}s",
            ) from exc
        except OSError as exc:
            raise SourceExtractionError(
                message_en="Failed to launch yt-dlp.exe process.",
                details=redact_sensitive_text(str(exc)),
            ) from exc

        if proc.returncode != 0:
            safe_stderr = redact_sensitive_text((proc.stderr or "").strip())
            if safe_stderr and (
                "timed out" in safe_stderr.lower()
                or "timeout" in safe_stderr.lower()
            ):
                raise SourceNetworkTimeoutError(
                    message_en="Network connection timed out while fetching data from YouTube.",
                    details=safe_stderr,
                )
            raise SourceExtractionError(
                details=safe_stderr or f"yt-dlp exited with code {proc.returncode}",
            )

        stdout_str = (proc.stdout or "").strip()
        if not stdout_str:
            raise SourceExtractionError(
                message_en="yt-dlp returned empty output.",
            )

        # If multiple JSON lines are emitted, parse the first valid JSON object
        first_line = stdout_str.splitlines()[0].strip()
        try:
            parsed = json.loads(first_line)
            if not isinstance(parsed, dict):
                raise ValueError("Expected JSON object from yt-dlp.")
            return parsed
        except (json.JSONDecodeError, ValueError) as exc:
            raise SourceExtractionError(
                message_en="Failed to parse JSON metadata returned by yt-dlp.",
                details=redact_sensitive_text(str(exc)),
            ) from exc

    def extract_entries(
        self,
        url: str,
        cookies_path: Optional[Path] = None,
    ) -> list[RawSourceEntry]:
        """Validate URL and extract flat list of RawSourceEntry for Single Track, Playlist, or Album."""
        clean_url = validate_youtube_url(url)
        data = self._run_json_command(
            ["--flat-playlist", "--dump-single-json", clean_url],
            cookies_path=cookies_path,
        )
        return parse_flat_entries(data, original_url=clean_url)

    def fetch_track_info(
        self,
        entry_url: str,
        cookies_path: Optional[Path] = None,
    ) -> RawTrackInfo:
        """Fetch full metadata and available audio formats for a single track in one call."""
        clean_url = validate_youtube_url(entry_url)
        data = self._run_json_command(
            ["--no-playlist", "--dump-single-json", clean_url],
            cookies_path=cookies_path,
        )
        return parse_track_info(data, entry_url=clean_url)

    def plan_stream(self, info: RawTrackInfo) -> StreamPlan:
        """Select optimal audio stream and processing mode according to DEC-033 (TC-024).

        - Prefer AAC-LC ('mp4a.40.2' in 'm4a' container) -> AudioProcessMode.REMUX_AAC
        - Otherwise select highest-bitrate audio stream -> AudioProcessMode.ENCODE_AAC_LC
        """
        valid_formats = [
            f
            for f in info.audio_formats
            if f.format_id and f.acodec and f.acodec.lower() != "none"
        ]
        if not valid_formats:
            raise SourceExtractionError(
                message_en="No audio streams are available for this track.",
                details=f"url={info.entry_url}",
            )

        aac_lc_m4a = [
            f
            for f in valid_formats
            if (f.acodec == "mp4a.40.2" or f.acodec.startswith("mp4a.40.2"))
            and f.ext.lower() == "m4a"
        ]
        if aac_lc_m4a:
            best_aac = max(aac_lc_m4a, key=lambda f: f.abr or 0.0)
            return StreamPlan(
                format_id=best_aac.format_id,
                mode=AudioProcessMode.REMUX_AAC,
            )

        best_other = max(valid_formats, key=lambda f: f.abr or 0.0)
        return StreamPlan(
            format_id=best_other.format_id,
            mode=AudioProcessMode.ENCODE_AAC_LC,
        )

    def download_stream(
        self,
        entry_url: str,
        plan: StreamPlan,
        temp_dir: Path,
        progress_cb: Optional[ProgressCallback] = None,
        cancel_event: Optional[Event] = None,
        cookies_path: Optional[Path] = None,
    ) -> Path:
        """Download the planned audio stream into `temp_dir` with progress reporting and cancellation support."""
        clean_url = validate_youtube_url(entry_url)
        temp_dir_path = Path(temp_dir)
        temp_dir_path.mkdir(parents=True, exist_ok=True)

        if cancel_event is not None and cancel_event.is_set():
            raise TaskCancelledError()

        output_template = str(temp_dir_path / "raw_stream.%(ext)s")
        args = [
            "--no-playlist",
            "-f",
            plan.format_id,
            "--newline",
            "--progress-template",
            "download:PLADAZ_PROG:%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
            "-o",
            output_template,
            clean_url,
        ]
        cmd = self._build_base_cmd(cookies_path=cookies_path) + args

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
            raise SourceExtractionError(
                message_en="Failed to start yt-dlp download process.",
                details=redact_sensitive_text(str(exc)),
            ) from exc

        start_time = time.monotonic()
        stderr_output = ""
        try:
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                if cancel_event is not None and cancel_event.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    raise TaskCancelledError()

                if (time.monotonic() - start_time) > self.download_timeout_sec:
                    proc.kill()
                    raise SourceNetworkTimeoutError(
                        message_en="Download timed out.",
                        details=f"timeout={self.download_timeout_sec}s",
                    )

                line = raw_line.strip()
                if progress_cb is not None and "PLADAZ_PROG:" in line:
                    self._dispatch_progress_line(line, progress_cb)

            _, stderr_output = proc.communicate(timeout=10)
        except TaskCancelledError:
            raise
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            raise SourceNetworkTimeoutError(
                message_en="Download process timed out while finishing.",
            ) from exc

        if cancel_event is not None and cancel_event.is_set():
            raise TaskCancelledError()

        if proc.returncode != 0:
            safe_err = redact_sensitive_text((stderr_output or "").strip())
            raise SourceExtractionError(
                message_en="Failed to download audio stream from YouTube.",
                details=safe_err or f"yt-dlp exited with code {proc.returncode}",
            )

        downloaded_files = [
            p
            for p in temp_dir_path.glob("raw_stream.*")
            if p.is_file() and not p.name.endswith(".part")
        ]
        if not downloaded_files:
            raise SourceExtractionError(
                message_en="yt-dlp finished without producing an audio file in Temp.",
            )
        return downloaded_files[0]

    @staticmethod
    def _dispatch_progress_line(
        line: str,
        progress_cb: ProgressCallback,
    ) -> None:
        try:
            payload = line.split("PLADAZ_PROG:", 1)[1]
            parts = payload.split("|")
            pct_raw = parts[0].strip().replace("%", "").strip()
            pct = float(pct_raw) if pct_raw and pct_raw != "NA" else 0.0
            speed_str = parts[1].strip() if len(parts) > 1 else ""
            eta_str = parts[2].strip() if len(parts) > 2 else ""
            progress_cb(max(0.0, min(100.0, pct)), speed_str, eta_str)
        except (ValueError, IndexError):
            pass

    def get_version(self, binary_path: Optional[Path] = None) -> Optional[str]:
        """Run `<binary_path> --version` and return the version string, or None if unavailable."""
        target = Path(binary_path) if binary_path is not None else self.ytdlp_path
        if not target.exists():
            return None
        try:
            proc = subprocess.run(
                [str(target), "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15.0,
                shell=False,
                creationflags=_subprocess_creation_flags(),
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip().splitlines()[0].strip()
        except (OSError, subprocess.SubprocessError):
            pass
        return None

    def update_ytdlp(self) -> UpdateResult:
        """Safely update standalone yt-dlp.exe via temporary download + --version verification + os.replace (DEC-038, TC-031)."""
        old_version = self.get_version(self.ytdlp_path)
        self.ytdlp_path.parent.mkdir(parents=True, exist_ok=True)
        suffix = self.ytdlp_path.suffix or ".exe"
        tmp_path = self.ytdlp_path.with_name(f"{self.ytdlp_path.stem}.tmp{suffix}")

        try:
            self._binary_downloader(self.update_url, tmp_path)
            if not tmp_path.exists() or tmp_path.stat().st_size <= 0:
                raise OSError(f"Downloaded temporary binary '{tmp_path.name}' is missing or empty.")

            new_version = self.get_version(tmp_path)
            if not new_version:
                raise OSError(
                    f"Downloaded temporary binary '{tmp_path.name}' failed '--version' verification check."
                )

            os.replace(tmp_path, self.ytdlp_path)
            msg = f"Updated yt-dlp.exe successfully from {old_version or 'none'} to {new_version}."
            if self._logger:
                self._logger.info("DownloadSourceAdapter", msg)
            return UpdateResult(
                success=True,
                old_version=old_version,
                new_version=new_version,
                message=msg,
            )
        except Exception as exc:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            err_msg = f"Failed to update yt-dlp.exe: {exc}"
            if self._logger:
                self._logger.error(
                    component="DownloadSourceAdapter",
                    message=err_msg,
                    error_code=ErrorCode.ERR_YTDLP_UPDATE_FAILED,
                )
            return UpdateResult(
                success=False,
                old_version=old_version,
                new_version=None,
                message=err_msg,
            )
