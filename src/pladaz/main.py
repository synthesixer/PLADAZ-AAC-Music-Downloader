"""PLADAZ Application Shell and pywebview Entry Point (SYSTEM_DESIGN.md 2.4, 2.6, 3.6)."""

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, Optional

from pladaz import __version__
from pladaz.bridge.api import BridgeAPI
from pladaz.bridge.events import EventDispatcher
from pladaz.paths import AppPaths, resolve_app_paths
from pladaz.services.audio_processor import AudioProcessingService
from pladaz.services.config_store import (
    CONFIG_KEY_MUSICBRAINZ_USER_AGENT,
    ConfigHistoryStore,
)
from pladaz.services.folder_organizer import SmartFolderOrganizer
from pladaz.services.logger import PladazLogger
from pladaz.services.metadata_matcher import (
    HttpExternalMetadataFetcher,
    TemporaryExactMetadataMatcher,
)
from pladaz.services.metadata_service import MetadataAlbumArtService
from pladaz.services.output_validator import OutputValidator
from pladaz.services.queue_manager import DownloadQueueManager
from pladaz.services.sd_card_manager import SDCardManager
from pladaz.services.source_adapter import DownloadSourceAdapter

DEFAULT_WINDOW_WIDTH: int = 1280
DEFAULT_WINDOW_HEIGHT: int = 820
MIN_WINDOW_SIZE: tuple[int, int] = (380, 600)


@dataclass
class AppContext:
    """Container holding initialized application services and BridgeAPI."""

    paths: AppPaths
    logger: PladazLogger
    config_store: ConfigHistoryStore
    events: EventDispatcher
    sd_card_manager: SDCardManager
    folder_organizer: SmartFolderOrganizer
    metadata_service: MetadataAlbumArtService
    audio_processor: AudioProcessingService
    output_validator: OutputValidator
    source_adapter: DownloadSourceAdapter
    queue_manager: DownloadQueueManager
    bridge: BridgeAPI

    _closed: bool = False

    def shutdown(self) -> None:
        """Stop the queue (discard Queued tasks, cancel and wait for the active one), clean Temp, and close logs.

        Safe to call more than once: the window-closed hook and main()'s finally both call it.
        """
        if self._closed:
            return
        self._closed = True
        try:
            self.queue_manager.shutdown()
        except Exception:
            pass
        try:
            self.logger.info("AppShell", "Application shutting down cleanly.")
            self.logger.close()
        except Exception:
            pass


def create_app_context(paths: Optional[AppPaths] = None) -> AppContext:
    """Execute the PLADAZ startup sequence and wire all services + BridgeAPI (SYSTEM_DESIGN.md 3.6).

    Startup sequence:
    1. Resolve portable & bundled paths (`AppPaths`).
    2. Initialize rotating file logger (`logs/pladaz.log`).
    3. Load `config.json` and `history.json` (auto-recovering corrupt files with backup).
    4. Clean leftover files in `temp/` via `DownloadQueueManager(..., clean_temp_on_init=True)`.
    5. Construct `BridgeAPI` exposing initial state (including `disclaimer_accepted` for Board 04
       and `ytdlp_status` for Board 09).
    """
    resolved_paths = paths or resolve_app_paths()
    logger = PladazLogger(log_dir=resolved_paths.logs_dir)
    logger.info(
        "AppShell",
        f"Starting PLADAZ v{__version__} (app_root={resolved_paths.app_root})",
    )

    config_store = ConfigHistoryStore(base_dir=resolved_paths.app_root, logger=logger)
    # Trigger startup load & validation of config.json and history.json (TC-030)
    cfg = config_store.load_config()
    config_store.load_history()

    # If cookies_file_path is configured and exists, register its secret values in the log filter
    raw_cookies = cfg.get("cookies_file_path")
    if raw_cookies and isinstance(raw_cookies, str):
        cookies_path = Path(raw_cookies)
        if cookies_path.exists() and cookies_path.is_file():
            try:
                logger.redaction_filter.register_cookies_file_content(
                    cookies_path.read_text(encoding="utf-8", errors="ignore")
                )
            except OSError:
                pass

    events = EventDispatcher()
    sd_card_manager = SDCardManager(logger=logger)
    folder_organizer = SmartFolderOrganizer()
    metadata_matcher = TemporaryExactMetadataMatcher()
    # Read the User-Agent from config.json on every MusicBrainz call so a value saved in Settings applies without a restart
    external_fetcher = HttpExternalMetadataFetcher(
        musicbrainz_user_agent_provider=lambda: config_store.load_config().get(
            CONFIG_KEY_MUSICBRAINZ_USER_AGENT
        ),
        logger=logger,
    )
    metadata_service = MetadataAlbumArtService(
        matcher=metadata_matcher,
        external_fetcher=external_fetcher,
        logger=logger,
    )
    audio_processor = AudioProcessingService(
        ffmpeg_path=resolved_paths.ffmpeg_path,
        logger=logger,
    )
    output_validator = OutputValidator()
    source_adapter = DownloadSourceAdapter(
        ytdlp_path=resolved_paths.ytdlp_path,
        logger=logger,
    )
    queue_manager = DownloadQueueManager(
        source_adapter=source_adapter,
        metadata_service=metadata_service,
        folder_organizer=folder_organizer,
        audio_processor=audio_processor,
        output_validator=output_validator,
        sd_card_manager=sd_card_manager,
        config_store=config_store,
        event_dispatcher=events,
        temp_root=resolved_paths.temp_dir,
        logger=logger,
        clean_temp_on_init=True,
    )
    bridge = BridgeAPI(
        queue_manager=queue_manager,
        source_adapter=source_adapter,
        sd_card_manager=sd_card_manager,
        config_store=config_store,
        log_file_path=resolved_paths.log_file,
        ffmpeg_path=resolved_paths.ffmpeg_path,
    )

    return AppContext(
        paths=resolved_paths,
        logger=logger,
        config_store=config_store,
        events=events,
        sd_card_manager=sd_card_manager,
        folder_organizer=folder_organizer,
        metadata_service=metadata_service,
        audio_processor=audio_processor,
        output_validator=output_validator,
        source_adapter=source_adapter,
        queue_manager=queue_manager,
        bridge=bridge,
    )


def _attach_window_callbacks(window: Any, webview_mod: Any, ctx: AppContext) -> None:
    """Bind native file/folder dialogs, event dispatcher, and window lifecycle hooks."""
    ctx.events.set_window(window)

    def _pick_cookies_file() -> Optional[str]:
        res = window.create_file_dialog(
            webview_mod.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("Cookies File (*.txt)", "All files (*.*)"),
        )
        if res and len(res) > 0:
            return str(res[0])
        return None

    def _pick_folder() -> Optional[str]:
        res = window.create_file_dialog(webview_mod.FOLDER_DIALOG)
        if res and len(res) > 0:
            return str(res[0])
        return None

    def _pick_exe() -> Optional[str]:
        res = window.create_file_dialog(
            webview_mod.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("Executable (*.exe)", "All files (*.*)"),
        )
        if res and len(res) > 0:
            return str(res[0])
        return None

    def _quit_window() -> None:
        try:
            window.destroy()
        except Exception:
            pass

    ctx.bridge.set_dialog_callbacks(
        file_dialog_fn=_pick_cookies_file,
        folder_dialog_fn=_pick_folder,
        exe_dialog_fn=_pick_exe,
        quit_fn=_quit_window,
    )

    def _on_closed() -> None:
        ctx.events.set_window(None)
        ctx.shutdown()

    try:
        window.events.closed += _on_closed
    except Exception:
        pass


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="PLADAZ Desktop Application")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Initialize AppContext, verify initial state and UI entry file, then exit.",
    )
    args = parser.parse_args(argv)

    ctx = create_app_context()
    if args.smoke_test:
        state = ctx.bridge.get_initial_state()
        ui_exists = ctx.paths.ui_entry.exists()
        ctx.shutdown()
        if not state.get("success") or not ui_exists:
            return 1
        print(f"PLADAZ_SMOKE_OK v{state.get('version')} ui={ctx.paths.ui_entry}")
        return 0

    import webview  # type: ignore[import-untyped]

    ui_url = (
        ctx.paths.ui_entry.as_uri()
        if ctx.paths.ui_entry.exists()
        else str(ctx.paths.ui_entry)
    )
    window = webview.create_window(
        title="PLADAZ — Personal Music Downloader",
        url=ui_url,
        js_api=ctx.bridge,
        width=DEFAULT_WINDOW_WIDTH,
        height=DEFAULT_WINDOW_HEIGHT,
        min_size=MIN_WINDOW_SIZE,
        background_color="#C9BCF5",
    )
    _attach_window_callbacks(window, webview, ctx)
    try:
        webview.start(debug=False)
    finally:
        ctx.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())

