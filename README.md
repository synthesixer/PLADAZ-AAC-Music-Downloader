# PLADAZ — Personal Music Downloader & Organizer for SNOWSKY ECHO DAP

**PLADAZ** is a portable Windows desktop application (`Python 3.11+`, `pywebview`, `yt-dlp.exe`, `FFmpeg`, `mutagen`, `Pillow`, `psutil`) that downloads audio from **YouTube** and **YouTube Music** into **AAC-LC (`mp4a.40.2`) inside `.m4a`** containers with **9 MP4 metadata fields** and **800×800 (1:1) JPEG cover art**, organized cleanly onto a **Micro SD Card** (`<Destination>/<Album Artist>/<Album>/<TrackNo - ><Title>.m4a`).

---

## 1. Architecture & Key Design Rules

- **Frontend / App Shell:** `pywebview` (Edge WebView2 on Windows 10/11) serving offline HTML/CSS/JS (`ui/index.html`, `ui/app.built.css`, `ui/js/bridge.js`, `ui/js/app.js`, and 163 bundled `.woff2` font subsets in `ui/fonts/` under SIL OFL-1.1 — zero CDN requests at runtime, `DEC-029`).
- **4 Strict Task Statuses (`DEC-025`):** `Queued`, `Downloading`, `Completed`, `Failed`.
- **10 Pipeline Stages inside `Downloading`:**
  1. `checking_sd`
  2. `fetching_info`
  3. `resolving_metadata`
  4. `checking_duplicate`
  5. `waiting_conflict`
  6. `downloading_stream`
  7. `processing_audio`
  8. `tagging`
  9. `validating`
  10. `copying`
- **Cover Art Pipeline:** Extracted from YouTube stream thumbnail metadata (with MusicBrainz search fallback via `HttpExternalMetadataFetcher`), normalized to 800×800 JPEG (1:1), and embedded into the M4A atom `covr`. Missing cover art when `require_album_art = false` produces a `! No cover` (`WARN_VALIDATOR_NO_COVER`) warning badge on a `Completed` task — never a 5th task status.
- **Pure-Python Audio Validation (No `ffprobe.exe`):** Validation is handled directly in pure Python via `mutagen.mp4.MP4` and `AudioValidatorService`, inspecting AAC-LC (`mp4a.40.2`) codec profile, sample rate, channels, bit depth, MP4 atom structure (`moov`, `trak`, `mdia`, `minf`, `stbl`, `stsd`), and embedded cover art. `ffprobe.exe` is completely omitted from the distribution, saving ~227.6 MB.
- **Portable Storage & Binary Management (`DEC-023`, `DEC-038`):**
  - `config.json`, `history.json`, `logs/pladaz.log`, `temp/`, and `PLADAZ.exe` are located in the application root directory.
  - Runtime binaries (`ffmpeg.exe` and `yt-dlp.exe`) are bundled inside `_internal/bin/` (with fallback resolution to root `yt-dlp.exe` or `bin/yt-dlp.exe` supported).
  - In PyInstaller `--onedir` mode on Windows, `_internal/bin/yt-dlp.exe` is a standard filesystem file that can be updated in-place via `DownloadSourceAdapter.update_ytdlp()` (`yt-dlp.tmp.exe` + `--version` check + `os.replace()`) without permission issues and without cluttering the application root.

---

## 2. Development Setup

### Prerequisites
- **Windows 10 / 11 (64-bit)** with Microsoft Edge WebView2 Runtime installed
- **Python 3.11+**
- **Node.js 18+** (only required at build time when modifying `ui_src/input.css` or `ui/index.html`)
- **FFmpeg** (`ffmpeg.exe` in `_internal/bin/`, `bin/`, or system `PATH`) and **`yt-dlp.exe`** (in `_internal/bin/`, project root, or system `PATH`)

### Install Python Dependencies
```powershell
python -m venv venv
.\venv\Scripts\pip.exe install -r requirements.txt
.\venv\Scripts\pip.exe install -e .
```

### Rebuild Offline Tailwind CSS (`ui_src/` → `ui/app.built.css`)
```powershell
npm install
npm run build:css
```

### Run Automated Tests (`pytest`)
```powershell
.\venv\Scripts\pytest.exe
```

### Run Application in Development Mode
```powershell
.\venv\Scripts\python.exe -m pladaz.main
```

---

## 3. Building Portable Windows `.exe` (`PyInstaller --onedir`)

Build the self-contained `dist/PLADAZ/` folder using `pladaz.spec`:

```powershell
.\venv\Scripts\pyinstaller.exe --noconfirm --clean pladaz.spec
```

### Output Layout (`dist/PLADAZ/`)
```text
dist/PLADAZ/
├── PLADAZ.exe               # Main Windows GUI executable (no console window)
├── README.md                # Quick start and instructions
├── LICENSE-THIRD-PARTY.txt  # Third-party open source notices & licenses
├── config.json              # Created automatically on first launch
├── history.json             # Created automatically on first launch
├── logs/
│   └── pladaz.log           # Rotating log file (sensitive cookies/tokens redacted)
├── temp/                    # Per-task staging folder (cleaned automatically on startup/exit)
└── _internal/               # Bundled Python runtime, ui/ assets, fonts, and binaries
    └── bin/
        ├── ffmpeg.exe       # Bundled FFmpeg transcode & muxing tool (~166 MB)
        └── yt-dlp.exe       # Bundled extractor (~17.8 MB, updateable in-app per DEC-038)
```

> [!NOTE]
> Git repository hygiene: `.gitignore` is configured to prevent committing large binaries (`*.exe`), `dist/`, `build/`, `venv/`, and `node_modules/`. Application distributions are published via GitHub Releases (supporting assets up to 2 GB).

---

## 4. QA & Regression Testing (Phase 5)

### Run Regression Suite Script (`IR-021` / `TC-021`)
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1
```
*(Runs unit, integration, and offline E2E suites with 71 passed tests (the live-network test is excluded), exiting with non-zero on failure).*

### Run It Automatically on Every Commit
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_git_hooks.ps1
```
*(Installs git `pre-commit` and `pre-push` hooks that run `run_tests.ps1` and block the commit or push on failure. Hooks live in `.git/hooks/`, which git does not version, so run this once in every clone.)*

### Verify Files on Micro SD Card (Read-Only)
```powershell
.\venv\Scripts\python.exe scripts\verify_sd_card.py <SD_DRIVE_PATH>
```
*(Inspects folder structure, filename sanitization, AAC-LC codec, MP4 atoms, 800×800 JPEG cover art, and checks for orphaned `.pladaz-tmp` files).*
