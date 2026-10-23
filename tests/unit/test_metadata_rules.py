"""Unit tests for MetadataAlbumArtService (TC-004, TC-005, TC-006, TC-007, TC-011, TC-026)."""

from io import BytesIO
from pathlib import Path
from typing import Optional
import pytest

pytestmark = pytest.mark.unit
from mutagen.mp4 import MP4, MP4Cover
from PIL import Image

from pladaz.domain.errors import ErrorCode, MetadataTaggingError
from pladaz.domain.models import ExternalMetadata, RawTrackInfo, TrackMetadata
from pladaz.services.metadata_service import (
    ATOM_ALBUM,
    ATOM_ALBUM_ARTIST,
    ATOM_COVER,
    ATOM_DISC_NUMBER,
    ATOM_GENRE,
    ATOM_TITLE,
    ATOM_TRACK_ARTIST,
    ATOM_TRACK_NUMBER,
    ATOM_YEAR,
    MetadataAlbumArtService,
)


class FakeExactMatcher:
    """Fake implementation of MetadataMatcherProtocol for testing DEC-035 without fixing TBA-026."""

    def is_match(
        self,
        src_title: str,
        src_artist: str,
        cand_title: str,
        cand_artist: str,
    ) -> bool:
        return (src_title == cand_title) and (src_artist == cand_artist)


class FakeExternalFetcher:
    """Fake implementation of ExternalMetadataFetcherProtocol for offline unit tests."""

    def __init__(
        self,
        candidates: Optional[list[ExternalMetadata]] = None,
        cover_bytes: Optional[bytes] = None,
        should_raise: Optional[Exception] = None,
    ) -> None:
        self.candidates = candidates or []
        self.cover_bytes = cover_bytes
        self.should_raise = should_raise

    def fetch_candidates(self, info: RawTrackInfo) -> list[ExternalMetadata]:
        if self.should_raise is not None:
            raise self.should_raise
        return self.candidates

    def fetch_cover_bytes(self, url: str) -> Optional[bytes]:
        return self.cover_bytes


def test_tc004_core_metadata_tags_written_and_verified_with_uppercase_art_atom(
    sample_m4a_path: Path,
) -> None:
    """TC-004: Title (©nam), Track Artist (©ART), Album (©alb), and Album Artist (aART) are stored in UTF-8 and read back."""
    service = MetadataAlbumArtService()
    meta = TrackMetadata(
        title="夜に駆ける (Racing into the Night)",
        track_artist="YOASOBI feat. Ikura",
        album="THE BOOK",
        album_artist="YOASOBI",
    )
    service.write_m4a_tags(sample_m4a_path, meta)

    mp4 = MP4(sample_m4a_path)
    assert mp4.tags is not None
    assert mp4.tags[ATOM_TITLE] == ["夜に駆ける (Racing into the Night)"]
    assert mp4.tags[ATOM_TRACK_ARTIST] == ["YOASOBI feat. Ikura"]
    assert ATOM_TRACK_ARTIST == "\xa9ART"
    assert "\xa9art" not in mp4.tags
    assert mp4.tags[ATOM_ALBUM] == ["THE BOOK"]
    assert mp4.tags[ATOM_ALBUM_ARTIST] == ["YOASOBI"]


def test_tc005_track_number_and_disc_number_atoms(
    sample_m4a_path: Path,
) -> None:
    """TC-005: Track Number (trkn) and Disc Number (disk) tuples are written and read back accurately."""
    service = MetadataAlbumArtService()
    meta = TrackMetadata(
        title="Track 07",
        track_number=7,
        total_tracks=12,
        disc_number=2,
        total_discs=3,
    )
    service.write_m4a_tags(sample_m4a_path, meta)

    mp4 = MP4(sample_m4a_path)
    assert mp4.tags is not None
    assert mp4.tags[ATOM_TRACK_NUMBER] == [(7, 12)]
    assert mp4.tags[ATOM_DISC_NUMBER] == [(2, 3)]


def test_tc006_year_and_genre_atoms(
    sample_m4a_path: Path,
) -> None:
    """TC-006: Year (©day) and Genre (©gen) are written and read back accurately."""
    service = MetadataAlbumArtService()
    meta = TrackMetadata(
        title="City Pop Tune",
        year="1984",
        genre="City Pop / J-Pop",
    )
    service.write_m4a_tags(sample_m4a_path, meta)

    mp4 = MP4(sample_m4a_path)
    assert mp4.tags is not None
    assert mp4.tags[ATOM_YEAR] == ["1984"]
    assert mp4.tags[ATOM_GENRE] == ["City Pop / J-Pop"]


def test_tc007_process_cover_800x800_jpeg_and_embed_in_covr_atom(
    sample_m4a_path: Path,
    sample_wide_png_bytes: bytes,
) -> None:
    """TC-007 (DEC-021): Non-square PNG is converted to 1:1 800x800 RGB JPEG and embedded in covr atom."""
    service = MetadataAlbumArtService()
    jpeg_bytes = service.process_cover(sample_wide_png_bytes)

    with Image.open(BytesIO(jpeg_bytes)) as img:
        assert img.format == "JPEG"
        assert img.mode == "RGB"
        assert img.size == (800, 800)

    meta = TrackMetadata(
        title="Song With Cover",
        cover_jpeg=jpeg_bytes,
    )
    service.write_m4a_tags(sample_m4a_path, meta)

    mp4 = MP4(sample_m4a_path)
    assert mp4.tags is not None
    assert ATOM_COVER in mp4.tags
    covr_list = mp4.tags[ATOM_COVER]
    assert len(covr_list) == 1
    assert covr_list[0].imageformat == MP4Cover.FORMAT_JPEG
    assert bytes(covr_list[0]) == jpeg_bytes


def test_tc011_missing_metadata_fields_never_write_fake_values(
    sample_m4a_path: Path,
) -> None:
    """TC-011 (Plan 7.3, DEC-015):
    - When Album Artist is missing, fallback 1 in metadata is Track Artist.
    - When both Album Artist and Track Artist are missing, fallback 2 is None (atom not written; NEVER 'Unknown Artist').
    - Other missing fields are omitted from M4A atoms.
    """
    service = MetadataAlbumArtService()

    # Subcase A: Album Artist missing, Track Artist present -> Album Artist falls back to Track Artist
    raw_a = RawTrackInfo(
        entry_url="https://music.youtube.com/watch?v=aaa",
        title="Track A",
        artist="Solo Artist",
        album=None,
        album_artist=None,
        track_number=None,
        disc_number=None,
        release_year=None,
        genre=None,
        thumbnail_url=None,
        audio_formats=[],
    )
    resolved_a = service.resolve_metadata(raw_a)
    assert resolved_a.track_artist == "Solo Artist"
    assert resolved_a.album_artist == "Solo Artist"
    assert resolved_a.album is None

    service.write_m4a_tags(sample_m4a_path, resolved_a)
    mp4_a = MP4(sample_m4a_path)
    assert mp4_a.tags is not None
    assert mp4_a.tags[ATOM_TITLE] == ["Track A"]
    assert mp4_a.tags[ATOM_TRACK_ARTIST] == ["Solo Artist"]
    assert mp4_a.tags[ATOM_ALBUM_ARTIST] == ["Solo Artist"]
    assert ATOM_ALBUM not in mp4_a.tags
    assert ATOM_TRACK_NUMBER not in mp4_a.tags
    assert ATOM_DISC_NUMBER not in mp4_a.tags
    assert ATOM_YEAR not in mp4_a.tags
    assert ATOM_GENRE not in mp4_a.tags
    assert ATOM_COVER not in mp4_a.tags

    # Subcase B: Both Album Artist and Track Artist missing -> both omitted (no 'Unknown Artist' in file tags!)
    raw_b = RawTrackInfo(
        entry_url="https://www.youtube.com/watch?v=bbb",
        title="Track B",
        artist=None,
        album=None,
        album_artist=None,
        track_number=None,
        disc_number=None,
        release_year=None,
        genre=None,
        thumbnail_url=None,
        audio_formats=[],
    )
    resolved_b = service.resolve_metadata(raw_b)
    assert resolved_b.track_artist is None
    assert resolved_b.album_artist is None

    service.write_m4a_tags(sample_m4a_path, resolved_b)
    mp4_b = MP4(sample_m4a_path)
    assert mp4_b.tags is not None
    assert mp4_b.tags[ATOM_TITLE] == ["Track B"]
    assert ATOM_TRACK_ARTIST not in mp4_b.tags
    assert ATOM_ALBUM_ARTIST not in mp4_b.tags


def test_tc026_external_enrichment_acceptance_rules_with_fake_matcher() -> None:
    """TC-026 (DEC-035, TBA-026 via Fake Protocol):
    (a) When candidate title AND artist match via MetadataMatcherProtocol -> fills missing fields.
    (b) When candidate title or artist does NOT match -> does NOT fill any fields; missing fields remain None.
    """
    raw = RawTrackInfo(
        entry_url="https://music.youtube.com/watch?v=xyz",
        title="Stay With Me",
        artist="Miki Matsubara",
        album=None,
        album_artist=None,
        track_number=None,
        disc_number=None,
        release_year=None,
        genre=None,
        thumbnail_url=None,
        audio_formats=[],
    )

    # (a) Matching candidate
    matching_cand = ExternalMetadata(
        source="itunes",
        title="Stay With Me",
        artist="Miki Matsubara",
        album="Pocket Park",
        album_artist="Miki Matsubara",
        track_number=1,
        disc_number=1,
        genre="City Pop",
        year="1980",
    )
    service_match = MetadataAlbumArtService(
        matcher=FakeExactMatcher(),
        external_fetcher=FakeExternalFetcher(candidates=[matching_cand]),
    )
    meta_a = service_match.resolve_metadata(raw)
    assert meta_a.album == "Pocket Park"
    assert meta_a.track_number == 1
    assert meta_a.disc_number == 1
    assert meta_a.genre == "City Pop"
    assert meta_a.year == "1980"

    # (b) Non-matching candidate (different artist or different title)
    mismatched_cand = ExternalMetadata(
        source="itunes",
        title="Stay With Me",
        artist="Sam Smith",  # Artist mismatch!
        album="In the Lonely Hour",
        album_artist="Sam Smith",
        track_number=3,
        disc_number=1,
        genre="Pop",
        year="2014",
    )
    service_mismatch = MetadataAlbumArtService(
        matcher=FakeExactMatcher(),
        external_fetcher=FakeExternalFetcher(candidates=[mismatched_cand]),
    )
    meta_b = service_mismatch.resolve_metadata(raw)
    assert meta_b.album is None
    assert meta_b.track_number is None
    assert meta_b.genre is None
    assert meta_b.year is None
    assert meta_b.album_artist == "Miki Matsubara"  # Fallback 1 from raw.artist, NOT 'Sam Smith'


def test_external_enrichment_network_failure_logs_warning_and_does_not_fail() -> None:
    """SYSTEM_DESIGN.md 2.5(2) [Proposal]: When external API times out or fails, leave fields blank and record warning."""
    raw = RawTrackInfo(
        entry_url="https://music.youtube.com/watch?v=timeout",
        title="Offline Song",
        artist="Offline Artist",
        album=None,
        album_artist=None,
        track_number=None,
        disc_number=None,
        release_year=None,
        genre=None,
        thumbnail_url=None,
        audio_formats=[],
    )
    service = MetadataAlbumArtService(
        matcher=FakeExactMatcher(),
        external_fetcher=FakeExternalFetcher(should_raise=TimeoutError("API timeout")),
    )
    warnings: list[str] = []
    meta = service.resolve_metadata(raw, warnings_out=warnings)
    assert meta.title == "Offline Song"
    assert meta.album is None
    assert len(warnings) == 1
    assert ErrorCode.WARN_METADATA_ENRICH_UNAVAILABLE in warnings[0]

