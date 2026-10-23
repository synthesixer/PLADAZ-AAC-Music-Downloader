"""Unit tests for OutputValidator (TC-014, TC-020, TC-022, TC-023)."""

from pathlib import Path
from mutagen.mp4 import MP4, MP4Cover

from pladaz.domain.errors import ErrorCode
from pladaz.domain.models import TrackMetadata
from pladaz.services.metadata_service import ATOM_COVER, MetadataAlbumArtService
from pladaz.services.output_validator import (
    MISSING_COVER_WARNING_EN,
    OutputValidator,
)


def test_tc014_valid_aac_lc_m4a_with_metadata_and_cover_passes(
    sample_m4a_path: Path,
    sample_wide_png_bytes: bytes,
) -> None:
    """TC-014: Processed M4A file with AAC-LC audio, Title, and 800x800 JPEG cover passes validation."""
    meta_service = MetadataAlbumArtService()
    validator = OutputValidator()

    cover_jpeg = meta_service.process_cover(sample_wide_png_bytes)
    meta = TrackMetadata(
        title="Valid Song",
        track_artist="Valid Artist",
        album="Valid Album",
        album_artist="Valid Artist",
        cover_jpeg=cover_jpeg,
    )
    meta_service.write_m4a_tags(sample_m4a_path, meta)

    res = validator.validate(sample_m4a_path, require_cover=True)
    assert res.is_valid is True
    assert res.is_readable is True
    assert res.is_aac_lc is True
    assert res.has_title is True
    assert res.has_cover is True
    assert res.warnings == []
    assert res.error_code is None


def test_tc020_output_validator_rejects_corrupt_non_aac_and_missing_title_files(
    tmp_path: Path,
    sample_m4a_path: Path,
    sample_alac_path: Path,
) -> None:
    """TC-020: OutputValidator rejects 0-byte, non-existent, corrupt, non-AAC-LC (ALAC), and missing-Title files."""
    validator = OutputValidator()

    # 1. Non-existent file
    res_missing = validator.validate(tmp_path / "does_not_exist.m4a")
    assert res_missing.is_valid is False
    assert res_missing.error_code == ErrorCode.ERR_VALIDATOR_CORRUPT_FILE

    # 2. 0-byte file
    zero_file = tmp_path / "zero.m4a"
    zero_file.write_bytes(b"")
    res_zero = validator.validate(zero_file)
    assert res_zero.is_valid is False
    assert res_zero.error_code == ErrorCode.ERR_VALIDATOR_CORRUPT_FILE

    # 3. Corrupted random bytes file
    corrupt_file = tmp_path / "corrupt.m4a"
    corrupt_file.write_bytes(b"NOT_AN_MP4_CONTAINER_1234567890")
    res_corrupt = validator.validate(corrupt_file)
    assert res_corrupt.is_valid is False
    assert res_corrupt.error_code == ErrorCode.ERR_VALIDATOR_CORRUPT_FILE

    # 4. Non-AAC-LC M4A (ALAC codec inside valid MP4 container)
    res_alac = validator.validate(sample_alac_path)
    assert res_alac.is_valid is False
    assert res_alac.is_readable is True
    assert res_alac.is_aac_lc is False
    assert res_alac.error_code == ErrorCode.ERR_VALIDATOR_INVALID_CODEC

    # 5. Valid AAC-LC M4A but missing ©nam (Title) tag
    res_no_title = validator.validate(sample_m4a_path)
    assert res_no_title.is_valid is False
    assert res_no_title.is_readable is True
    assert res_no_title.is_aac_lc is True
    assert res_no_title.has_title is False
    assert res_no_title.error_code == ErrorCode.ERR_VALIDATOR_MISSING_TITLE


def test_tc022_missing_cover_with_default_switch_passes_with_warning(
    sample_m4a_path: Path,
) -> None:
    """TC-022 (DEC-031): When cover art is missing and require_cover=False (default), file passes with a warning."""
    meta_service = MetadataAlbumArtService()
    validator = OutputValidator()

    meta = TrackMetadata(title="Song Without Cover", cover_jpeg=None)
    meta_service.write_m4a_tags(sample_m4a_path, meta)

    res = validator.validate(sample_m4a_path, require_cover=False)
    assert res.is_valid is True
    assert res.is_readable is True
    assert res.is_aac_lc is True
    assert res.has_title is True
    assert res.has_cover is False
    assert res.error_code is None
    assert res.warnings == [MISSING_COVER_WARNING_EN]


def test_tc023_missing_cover_with_require_cover_true_fails_validation(
    sample_m4a_path: Path,
) -> None:
    """TC-023 (DEC-031): When cover art is missing and require_cover=True, validation fails with ERR_VALIDATOR_MISSING_COVER."""
    meta_service = MetadataAlbumArtService()
    validator = OutputValidator()

    meta = TrackMetadata(title="Song Requiring Cover", cover_jpeg=None)
    meta_service.write_m4a_tags(sample_m4a_path, meta)

    res = validator.validate(sample_m4a_path, require_cover=True)
    assert res.is_valid is False
    assert res.is_readable is True
    assert res.is_aac_lc is True
    assert res.has_title is True
    assert res.has_cover is False
    assert res.error_code == ErrorCode.ERR_VALIDATOR_MISSING_COVER


def test_corrupted_cover_bytes_in_covr_atom_fails_validation(
    sample_m4a_path: Path,
) -> None:
    """If covr atom is present but contains non-image bytes that Pillow cannot open, validator rejects it."""
    meta_service = MetadataAlbumArtService()
    validator = OutputValidator()

    meta = TrackMetadata(title="Song With Broken Cover", cover_jpeg=None)
    meta_service.write_m4a_tags(sample_m4a_path, meta)

    mp4 = MP4(sample_m4a_path)
    assert mp4.tags is not None
    mp4.tags[ATOM_COVER] = [MP4Cover(b"NOT_A_JPEG_IMAGE", imageformat=MP4Cover.FORMAT_JPEG)]
    mp4.save()

    res = validator.validate(sample_m4a_path, require_cover=False)
    assert res.is_valid is False
    assert res.error_code == ErrorCode.ERR_VALIDATOR_MISSING_COVER

