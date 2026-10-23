# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for PLADAZ (one-folder / --onedir mode per DEC-038 & Phase 4 Decision 4.3 ก.5).

- Bundles Python runtime, pladaz package, pre-built offline `ui/` assets, and `ffmpeg.exe`.
- Does NOT embed `yt-dlp.exe` inside the archive (DEC-038); instead places standalone `yt-dlp.exe`
  alongside `dist/PLADAZ/PLADAZ.exe` so it can be updated independently via `DownloadSourceAdapter.update_ytdlp()`.
"""

from pathlib import Path
import shutil

block_cipher = None

PROJECT_ROOT = Path(SPECPATH).resolve()
SRC_DIR = PROJECT_ROOT / "src"
UI_DIR = PROJECT_ROOT / "ui"

datas = [
    (str(UI_DIR), "ui"),
]

binaries = []
for tool_name in ("ffmpeg.exe", "yt-dlp.exe"):
    local_bin = PROJECT_ROOT / "bin" / tool_name
    root_bin = PROJECT_ROOT / tool_name
    if local_bin.exists():
        binaries.append((str(local_bin), "bin"))
    elif root_bin.exists():
        binaries.append((str(root_bin), "bin"))
    else:
        system_bin = shutil.which(tool_name) or shutil.which(Path(tool_name).stem)
        if system_bin:
            binaries.append((str(Path(system_bin).resolve()), "bin"))

a = Analysis(
    [str(SRC_DIR / "pladaz" / "main.py")],
    pathex=[str(SRC_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "webview",
        "clr",
        "mutagen",
        "mutagen.mp4",
        "PIL",
        "psutil",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PLADAZ",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PLADAZ",
)

# Clean up any legacy external yt-dlp.exe placed directly in dist_folder
dist_folder = Path(DISTPATH) / "PLADAZ"
legacy_external_ytdlp = dist_folder / "yt-dlp.exe"
if legacy_external_ytdlp.exists():
    try:
        legacy_external_ytdlp.unlink()
    except OSError:
        pass

