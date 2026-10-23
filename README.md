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
- **No Cover Art Warning Badge:** Missing cover art when `require_album_art = false` produces a `! No cover` (`WARN_VALIDATOR_NO_COVER`) warning badge on a `Completed` task — never a 5th task status.
- **Portable Storage (`DEC-023`, `DEC-038`):**
  - `config.json`, `history.json`, `logs/pladaz.log`, `temp/`, and standalone `yt-dlp.exe` are stored directly alongside `PLADAZ.exe` in the application folder.
  - `yt-dlp.exe` is kept external to the PyInstaller bundle so `DownloadSourceAdapter.update_ytdlp()` can update it in-place (`yt-dlp.tmp.exe` + `--version` check + `os.replace()`).

---

## 2. Development Setup

### Prerequisites
- **Windows 10 / 11 (64-bit)** with Microsoft Edge WebView2 Runtime installed
- **Python 3.11+**
- **Node.js 18+** (only required at build time when modifying `ui_src/input.css` or `ui/index.html`)
- **FFmpeg** (`ffmpeg.exe` in `bin/` or system `PATH`) and standalone **`yt-dlp.exe`** (in project root or `bin/yt-dlp.exe`)

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
├── PLADAZ.exe          # Main Windows GUI executable (no console window)
├── yt-dlp.exe          # External standalone extractor (updateable in-app per DEC-038)
├── config.json         # Created automatically on first launch
├── history.json        # Created automatically on first launch
├── logs/
│   └── pladaz.log      # Rotating log file (sensitive cookies/tokens redacted)
├── temp/               # Per-task staging folder (cleaned automatically on startup/exit)
└── _internal/          # Bundled Python runtime, ui/ assets, fonts, and bin/ffmpeg.exe
```

---

## 4. QA & Regression Testing (Phase 5)

### Run Regression Suite Script (`IR-021` / `TC-021`)
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1
```
*(Runs unit, integration, and fs suites with 55 passed tests, exiting with non-zero on failure).*

### Verify Files on Micro SD Card (Read-Only)
```powershell
.\venv\Scripts\python.exe scripts\verify_sd_card.py <SD_DRIVE_PATH>
```
*(Inspects folder structure, filename sanitization, AAC-LC codec, MP4 atoms, 800×800 JPEG cover art, and checks for orphaned `.pladaz-tmp` files).*
