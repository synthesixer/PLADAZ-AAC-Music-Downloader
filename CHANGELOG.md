# Changelog

All notable changes to the **PLADAZ** project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] - work after 1.0.0 (built into `dist/` from `main` at `a4ce579`, release candidate RC2)

### Added
- **Browser Authentication (DEC-052):** detect supported browsers (Firefox, Microsoft Edge, Google Chrome, Brave, Opera, Vivaldi, Chromium, Naver Whale) from the Windows registry and cookie-store presence, recommend one, and use `yt-dlp --cookies-from-browser` only after an explicit consent dialog. `cookies.txt` import stays as a fallback and takes priority when both are set.
- **Multi-link add (DEC-053):** the link box accepts one link per line; `enqueue_urls` processes every line and returns `failed_lines`, and only failed lines stay in the box.
- Clear History confirmation dialog; reasons shown under a disabled Start/Resume button.
- Regression hooks: git `pre-commit` and `pre-push` run `scripts/run_tests.ps1` (network tests excluded).
- Personal Use Disclaimer text on first launch (DEC-054; wording delegated by the owner).
- `scripts/measure_performance.py` for the TBA-023 criteria set in DEC-054 (start ≤ 5 s, post-download stages ≤ 30 s per 5-minute track).

### Changed
- **UX/UI (DEC-053):** action pink `#CC2982` (white text 5.0:1); lavender page bezels with Now Processing as the only pink bezel; pixel-window style for system dialogs; Conflict dialog with Keep Both as the primary action; Settings save automatically.
- **App exit (DEC-051):** queued tasks are discarded without history, the active task is cancelled, and the worker is joined before exit.
- Every copy to the SD card is staged as `.pladaz-tmp`, verified, then moved into place (previously only Overwrite).
- `update_config` accepts only `require_album_art`, `musicbrainz_user_agent` and `destination_path`; the MusicBrainz User-Agent is read on every call.

### Fixed
- Cancel and timeout now work while yt-dlp prints nothing; fallback encode prefers audio-only streams; concurrent history writes no longer lose entries; `verify_sd_card.py` reads `history.json` correctly.
- Unrelated download failures are no longer reported as browser-cookie errors.
- Accessibility: live-region announcements, progress bar semantics, names on icon buttons, Settings labels, dialog focus handling.

## [1.0.0] - 2026-10-23

### Added
- **Core Engine (Phase 2):**
  - `SmartFolderOrganizer`: Organizes downloaded music into `<Album Artist>/<Album>/<Title>.m4a` hierarchy with fallback to `'Unknown Artist'` and `'Unknown Album'`. Sanitizes Windows forbidden characters (`\\ / : * ? \" < > |` and control chars) and handles Windows `MAX_PATH` (> 259 chars) with safe rejection (`ERR_PATH_TOO_LONG`).
  - `MetadataAlbumArtService`: Writes and validates 8 MP4 atoms (`©nam`, `©ART`, `aART`, `©alb`, `trkn`, `disk`, `©day`, `©gen`) and 1:1 JPEG 800x800 px album art in `covr` atom using mutagen and Pillow.
  - `SDCardManager`: Detects removable drives, checks free space before download, and performs Copy & Verify with safe temporary `.pladaz-tmp` file staging for Overwrite operations.
  - `OutputValidator`: Strict validation ensuring audio is readable AAC-LC, mandatory Title atom is present, and album art matches user settings.
  - `PladazLogger`: Structured logging with `RotatingFileHandler` and automatic redaction of sensitive cookies, tokens, and credentials.
  - `ConfigHistoryStore`: JSON store for `config.json` and `history.json` with automatic backup and corrupted file recovery (`.corrupt`).
- **Audio & Download Pipeline (Phase 3):**
  - `DownloadSourceAdapter`: Orchestrates `yt-dlp.exe` and `ffmpeg.exe` for Single, Playlist, and Album URLs. Supports optional `cookies.txt` and safe in-app `yt-dlp.exe` updates with rollback.
  - `StreamPlan` selection: Direct remuxing (`-c:a copy`) for native AAC streams (`mp4a.40.2` in m4a) and encoding to AAC-LC for non-AAC streams.
  - `DownloadQueueManager`: Sequential Worker (1 track at a time) managing states: `Queued`, `Downloading`, `Completed`, `Failed` and 10 granular stages.
  - Periodic SD Card Watcher: Detects card removal mid-download and safely halts queue waiting for card re-insertion.
  - Conflict Resolution: Interactive Overwrite, Skip, and Keep Both (`Song (1).m4a`) dialog with `Apply to all in album` and `Apply to all in queue` scopes.
- **Frontend & App Shell (Phase 4):**
  - Modern pywebview App Shell (`1280x820` default, min `380x600`, responsive breakpoints at `1024px` and `640px`).
  - Fully offline Web UI with 19 approved boards, zero CDN dependencies, offline WOFF2 fonts (Dela Gothic One, Silkscreen, IBM Plex Sans Thai, IBM Plex Mono), and pre-built Tailwind CSS.
  - Two-way Native JS Bridge (`BridgeAPI` and `EventDispatcher`) supporting 6 real-time application events.
  - PyInstaller `--onedir` standalone packaging (`dist/PLADAZ/PLADAZ.exe`) with `yt-dlp.exe` placed externally for independent updates.
- **Verification & QA Tools (Phase 5):**
  - Automated Regression Test suite (`scripts/run_tests.ps1`) executing 55 unit, integration, and E2E tests in ~2 seconds.
  - Automated E2E Bridge API test harness (`tests/e2e/test_bridge_e2e.py`).
  - Read-only Micro SD Card validation utility (`scripts/verify_sd_card.py`).
  - Full Test Report and Traceability Matrix (`Doc/TEST_REPORT.md`).
  - User Guide (`Doc/USER_GUIDE.md`) and Known Limitations register (`Doc/KNOWN_LIMITATIONS.md`).

