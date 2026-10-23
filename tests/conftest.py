"""Shared pytest fixtures for PLADAZ unit and integration tests."""

from io import BytesIO
from pathlib import Path
import shutil
import pytest
from PIL import Image

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_AAC_LC_M4A = FIXTURES_DIR / "sample_aac_lc.m4a"
SAMPLE_ALAC_M4A = FIXTURES_DIR / "sample_alac.m4a"


@pytest.fixture
def sample_m4a_path(tmp_path: Path) -> Path:
    """Copy a clean, real AAC-LC .m4a file into tmp_path for a single test."""
    dest = tmp_path / "test_track.m4a"
    shutil.copyfile(SAMPLE_AAC_LC_M4A, dest)
    return dest


@pytest.fixture
def sample_alac_path(tmp_path: Path) -> Path:
    """Copy a real ALAC (non-AAC-LC) .m4a file into tmp_path for negative validator tests."""
    dest = tmp_path / "test_alac.m4a"
    shutil.copyfile(SAMPLE_ALAC_M4A, dest)
    return dest


@pytest.fixture
def sample_wide_png_bytes() -> bytes:
    """Create a 1200x600 RGBA PNG image in memory (left red, center green, right blue)."""
    img = Image.new("RGBA", (1200, 600), (0, 255, 0, 255))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

