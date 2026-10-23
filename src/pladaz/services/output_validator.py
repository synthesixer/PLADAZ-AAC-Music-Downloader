"""OutputValidator service (SYSTEM_DESIGN.md 2.5(5), IR-020, DEC-012, DEC-030, DEC-031, TC-014, TC-020, TC-022, TC-023)."""

from io import BytesIO
from pathlib import Path

from mutagen.mp4 import MP4
from PIL import Image, UnidentifiedImageError

from pladaz.domain.errors import ErrorCode
from pladaz.domain.models import ValidationResult
from pladaz.services.metadata_service import ATOM_COVER, ATOM_TITLE

EXPECTED_AAC_LC_CODEC: str = "mp4a.40.2"
MISSING_COVER_WARNING_EN: str = "Album art not found; saved without cover art."


class OutputValidator:
    """Validates processed M4A files before they are copied to the Micro SD Card or marked Completed."""

    def validate(
        self,
        path: Path,
        require_cover: bool = False,
    ) -> ValidationResult:
        """Validate readability, AAC-LC codec, required Title tag, and optional/required cover art."""
        file_path = Path(path)

        # 1. File exists, size > 0, and readable by mutagen.mp4.MP4
        try:
            if not file_path.exists() or not file_path.is_file():
                return ValidationResult(
                    is_valid=False,
                    is_readable=False,
                    error_code=ErrorCode.ERR_VALIDATOR_CORRUPT_FILE,
                )
            if file_path.stat().st_size <= 0:
                return ValidationResult(
                    is_valid=False,
                    is_readable=False,
                    error_code=ErrorCode.ERR_VALIDATOR_CORRUPT_FILE,
                )
            mp4 = MP4(file_path)
            if mp4.info is None:
                return ValidationResult(
                    is_valid=False,
                    is_readable=False,
                    error_code=ErrorCode.ERR_VALIDATOR_CORRUPT_FILE,
                )
        except Exception:
            return ValidationResult(
                is_valid=False,
                is_readable=False,
                error_code=ErrorCode.ERR_VALIDATOR_CORRUPT_FILE,
            )

        # 2. Verify AAC-LC codec ('mp4a.40.2') and audio length > 0
        codec = getattr(mp4.info, "codec", None)
        length = getattr(mp4.info, "length", 0.0)
        if codec != EXPECTED_AAC_LC_CODEC or length is None or float(length) <= 0.0:
            return ValidationResult(
                is_valid=False,
                is_readable=True,
                is_aac_lc=False,
                error_code=ErrorCode.ERR_VALIDATOR_INVALID_CODEC,
            )

        # 3. Verify required Title tag (©nam) is present and non-empty (DEC-030)
        tags = mp4.tags
        has_title = False
        if tags is not None and ATOM_TITLE in tags:
            title_list = tags[ATOM_TITLE]
            if (
                isinstance(title_list, list)
                and len(title_list) > 0
                and isinstance(title_list[0], str)
                and title_list[0].strip() != ""
            ):
                has_title = True

        if not has_title:
            return ValidationResult(
                is_valid=False,
                is_readable=True,
                is_aac_lc=True,
                has_title=False,
                error_code=ErrorCode.ERR_VALIDATOR_MISSING_TITLE,
            )

        # 4. Verify Cover Art (covr atom readable by Pillow, DEC-031)
        has_cover = False
        has_corrupt_cover_atom = False
        if tags is not None and ATOM_COVER in tags:
            covr_list = tags[ATOM_COVER]
            if isinstance(covr_list, list) and len(covr_list) > 0:
                try:
                    raw_cover = bytes(covr_list[0])
                    with Image.open(BytesIO(raw_cover)) as img:
                        img.verify()
                    has_cover = True
                except (UnidentifiedImageError, OSError, ValueError):
                    has_cover = False
                    has_corrupt_cover_atom = True

        if has_corrupt_cover_atom:
            return ValidationResult(
                is_valid=False,
                is_readable=True,
                is_aac_lc=True,
                has_title=True,
                has_cover=False,
                error_code=ErrorCode.ERR_VALIDATOR_MISSING_COVER,
            )

        if not has_cover:
            if require_cover:
                return ValidationResult(
                    is_valid=False,
                    is_readable=True,
                    is_aac_lc=True,
                    has_title=True,
                    has_cover=False,
                    error_code=ErrorCode.ERR_VALIDATOR_MISSING_COVER,
                )
            return ValidationResult(
                is_valid=True,
                is_readable=True,
                is_aac_lc=True,
                has_title=True,
                has_cover=False,
                warnings=[MISSING_COVER_WARNING_EN],
                error_code=None,
            )

        return ValidationResult(
            is_valid=True,
            is_readable=True,
            is_aac_lc=True,
            has_title=True,
            has_cover=True,
            warnings=[],
            error_code=None,
        )

