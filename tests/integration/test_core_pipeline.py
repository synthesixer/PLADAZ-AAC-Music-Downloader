"""End-to-end integration test for Phase 2 core modules working together (TC-021)."""

import ast
from pathlib import Path
import pytest

pytestmark = pytest.mark.integration

from mutagen.mp4 import MP4

from pladaz.domain.enums import TaskStatus
from pladaz.domain.models import ExternalMetadata, HistoryEntry, RawTrackInfo
from pladaz.services.config_store import (
    CONFIG_KEY_REQUIRE_ALBUM_ART,
    ConfigHistoryStore,
)
from pladaz.services.folder_organizer import SmartFolderOrganizer
from pladaz.services.logger import PladazLogger
from pladaz.services.metadata_service import (
    ATOM_ALBUM,
    ATOM_ALBUM_ARTIST,
    ATOM_COVER,
    ATOM_TITLE,
    ATOM_TRACK_ARTIST,
    MetadataAlbumArtService,
)
from pladaz.services.output_validator import OutputValidator
from pladaz.services.sd_card_manager import SDCardManager
from tests.integration.test_sd_card_manager import FakeDriveProbe
from tests.unit.test_metadata_rules import FakeExactMatcher, FakeExternalFetcher


def test_tc021_phase2_core_pipeline_end_to_end_regression(
    tmp_path: Path,
    sample_m4a_path: Path,
    sample_wide_png_bytes: bytes,
) -> None:
    """TC-021: Full Phase 2 core pipeline from RawTrackInfo -> Metadata & Cover -> Validator -> Organizer -> SD Card Copy & Verify -> History."""
    app_dir = tmp_path / "app"
    sd_root = tmp_path / "sdcard"
    sd_root.mkdir()

    logger = PladazLogger(log_dir=app_dir / "logs")
    try:
        config_store = ConfigHistoryStore(base_dir=app_dir, logger=logger)
        cfg = config_store.load_config()
        cfg["destination_path"] = str(sd_root)
        config_store.save_config(cfg)

        ext_cand = ExternalMetadata(
            source="itunes",
            title="Midnight Pretenders",
            artist="Tomoko Aran",
            album="Fuyukuukan",
            album_artist="Tomoko Aran",
            track_number=3,
            disc_number=1,
            genre="City Pop",
            year="1983",
            cover_url="https://example.invalid/cover.png",
        )
        meta_service = MetadataAlbumArtService(
            matcher=FakeExactMatcher(),
            external_fetcher=FakeExternalFetcher(
                candidates=[ext_cand],
                cover_bytes=sample_wide_png_bytes,
            ),
            logger=logger,
        )
        organizer = SmartFolderOrganizer()
        validator = OutputValidator()
        sd_manager = SDCardManager(
            drive_probe=FakeDriveProbe(root_dir=sd_root),
            logger=logger,
        )

        # 1. RawTrackInfo missing album/year/genre/cover -> enriched via Fake matcher
        raw_info = RawTrackInfo(
            entry_url="https://music.youtube.com/watch?v=aran1983",
            title="Midnight Pretenders",
            artist="Tomoko Aran",
            album=None,
            album_artist=None,
            track_number=None,
            disc_number=None,
            release_year=None,
            genre=None,
            thumbnail_url=None,
            audio_formats=[],
        )
        resolved_meta = meta_service.resolve_metadata(raw_info)
        assert resolved_meta.album == "Fuyukuukan"
        assert resolved_meta.album_artist == "Tomoko Aran"
        assert resolved_meta.cover_jpeg is not None

        # 2. Build target path on SD Card and check conflict
        target_path = organizer.build_target_path(sd_root, resolved_meta)
        assert (
            target_path
            == sd_root / "Tomoko Aran" / "Fuyukuukan" / "Midnight Pretenders.m4a"
        )
        assert organizer.check_conflict(target_path) is False

        # 3. Write tags and 800x800 JPEG cover to Temp M4A file
        meta_service.write_m4a_tags(sample_m4a_path, resolved_meta)

        # 4. Validate Temp M4A file before copying to SD Card
        val_result = validator.validate(
            sample_m4a_path,
            require_cover=bool(cfg[CONFIG_KEY_REQUIRE_ALBUM_ART]),
        )
        assert val_result.is_valid is True
        assert val_result.is_aac_lc is True
        assert val_result.has_title is True
        assert val_result.has_cover is True

        # 5. Copy & Verify to SD Card and clean up Temp
        final_sd_path = sd_manager.copy_and_verify(
            sample_m4a_path, target_path, overwrite=False
        )
        sd_manager.cleanup_temp(sample_m4a_path)
        assert not sample_m4a_path.exists()
        assert final_sd_path.exists()

        # 6. Verify tags on final SD card file
        mp4_sd = MP4(final_sd_path)
        assert mp4_sd.tags is not None
        assert mp4_sd.tags[ATOM_TITLE] == ["Midnight Pretenders"]
        assert mp4_sd.tags[ATOM_TRACK_ARTIST] == ["Tomoko Aran"]
        assert mp4_sd.tags[ATOM_ALBUM_ARTIST] == ["Tomoko Aran"]
        assert mp4_sd.tags[ATOM_ALBUM] == ["Fuyukuukan"]
        assert ATOM_COVER in mp4_sd.tags

        # 7. Append to history.json
        config_store.append_history(
            HistoryEntry(
                task_id="task-e2e-1",
                finished_at="2026-10-23T18:50:00Z",
                status=TaskStatus.COMPLETED,
                title=resolved_meta.title,
                album_artist=resolved_meta.album_artist,
                album=resolved_meta.album,
                target_file_path=str(final_sd_path),
                source_url=raw_info.entry_url,
                warnings=val_result.warnings,
                error_code=None,
            )
        )
        history = config_store.load_history()
        assert len(history) == 1
        assert history[0].status == TaskStatus.COMPLETED
    finally:
        logger.close()


def test_domain_layer_has_no_forbidden_third_party_imports() -> None:
    """Enforce Golden Rule 6 / SYSTEM_DESIGN.md 1.2: domain/ must not import mutagen, psutil, pywebview, Pillow, or yt_dlp."""
    domain_dir = Path(__file__).resolve().parents[2] / "src" / "pladaz" / "domain"
    forbidden_roots = {"mutagen", "psutil", "webview", "pywebview", "PIL", "yt_dlp"}

    for py_file in domain_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_pkg = alias.name.split(".")[0]
                    assert root_pkg not in forbidden_roots, (
                        f"Forbidden import '{alias.name}' found in {py_file}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                root_pkg = node.module.split(".")[0]
                assert root_pkg not in forbidden_roots, (
                    f"Forbidden import from '{node.module}' found in {py_file}"
                )

