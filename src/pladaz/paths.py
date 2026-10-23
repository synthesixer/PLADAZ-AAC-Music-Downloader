"""Portable path resolution for both development mode and PyInstaller frozen mode (SYSTEM_DESIGN.md 2.4, DEC-023, DEC-038)."""

from dataclasses import dataclass
from pathlib import Path
import shutil
import sys
from typing import Optional


@dataclass(frozen=True)
class AppPaths:
    """Resolved filesystem paths for PLADAZ runtime."""

    app_root: Path
    bundle_root: Path
    ui_dir: Path
    ui_entry: Path
    config_file: Path
    history_file: Path
    logs_dir: Path
    log_file: Path
    temp_dir: Path
    ytdlp_path: Path
    ffmpeg_path: Path
    ffprobe_path: Optional[Path] = None


def resolve_app_paths(
    frozen: Optional[bool] = None,
    executable_path: Optional[Path] = None,
    meipass_path: Optional[Path] = None,
    dev_root: Optional[Path] = None,
) -> AppPaths:
    """Resolve all portable and bundled paths for dev mode or PyInstaller frozen mode.

    - In frozen mode (`sys.frozen == True`):
      - `app_root` is the folder containing `PLADAZ.exe`. Mutable files (`config.json`, `history.json`,
        `logs/`, `temp/`) and standalone `yt-dlp.exe` (`DEC-038`) live directly under `app_root`.
      - `bundle_root` is `sys._MEIPASS` (in `--onedir`, `<app_root>/_internal`) if present, else `app_root`.
        Read-only bundled assets (`ui/`, bundled `bin/ffmpeg.exe`) are resolved from `bundle_root` (with fallback to `app_root`).
    - In dev mode (`sys.frozen == False`):
      - `app_root` and `bundle_root` both point to the repository root.
    """
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)

    if is_frozen:
        exe = Path(executable_path or sys.executable).resolve()
        app_root = exe.parent
        raw_meipass = meipass_path or getattr(sys, "_MEIPASS", None)
        bundle_root = Path(raw_meipass).resolve() if raw_meipass else app_root
    else:
        app_root = (
            Path(dev_root).resolve()
            if dev_root is not None
            else Path(__file__).resolve().parents[2]
        )
        bundle_root = app_root

    # UI directory: check bundle_root/ui first, fallback to app_root/ui
    ui_dir = bundle_root / "ui"
    if not ui_dir.exists() and (app_root / "ui").exists():
        ui_dir = app_root / "ui"
    ui_entry = ui_dir / "index.html"

    # Standalone yt-dlp.exe lives next to PLADAZ.exe in app_root (DEC-038, Board 09).
    # In dev mode, if app_root/yt-dlp.exe does not exist yet but app_root/bin/yt-dlp.exe exists, copy or use app_root/yt-dlp.exe.
    ytdlp_path = app_root / "yt-dlp.exe"
    if not is_frozen and not ytdlp_path.exists():
        dev_bin_ytdlp = app_root / "bin" / "yt-dlp.exe"
        if dev_bin_ytdlp.exists():
            try:
                shutil.copy2(dev_bin_ytdlp, ytdlp_path)
            except OSError:
                ytdlp_path = dev_bin_ytdlp

    # FFmpeg resolution: check bundle_root/bin, app_root/bin, app_root, then system PATH
    ffmpeg_path = _resolve_bundled_tool("ffmpeg.exe", bundle_root, app_root)
    ffprobe_path: Optional[Path] = None  # Not needed: PLADAZ uses mutagen for metadata and codec verification

    logs_dir = app_root / "logs"
    temp_dir = app_root / "temp"

    return AppPaths(
        app_root=app_root,
        bundle_root=bundle_root,
        ui_dir=ui_dir,
        ui_entry=ui_entry,
        config_file=app_root / "config.json",
        history_file=app_root / "history.json",
        logs_dir=logs_dir,
        log_file=logs_dir / "pladaz.log",
        temp_dir=temp_dir,
        ytdlp_path=ytdlp_path,
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
    )


def _resolve_bundled_tool(
    exe_name: str,
    bundle_root: Path,
    app_root: Path,
) -> Path:
    candidates = [
        bundle_root / "bin" / exe_name,
        bundle_root / exe_name,
        app_root / "bin" / exe_name,
        app_root / exe_name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    stem = Path(exe_name).stem
    which_hit = shutil.which(exe_name) or shutil.which(stem)
    if which_hit:
        return Path(which_hit).resolve()
    return bundle_root / "bin" / exe_name

