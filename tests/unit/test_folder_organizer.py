"""Unit tests for SmartFolderOrganizer (TC-002, TC-003, TC-011, TC-012, TC-013, TC-025, TC-026, TC-027)."""

from pathlib import Path
import pytest

from pladaz.domain.errors import ErrorCode, PathTooLongError
from pladaz.domain.models import TrackMetadata
from pladaz.services.folder_organizer import (
    MAX_COMPONENT_LENGTH,
    UNKNOWN_ALBUM_FOLDER,
    UNKNOWN_ARTIST_FOLDER,
    WINDOWS_MAX_PATH_CHARS,
    SmartFolderOrganizer,
)


@pytest.fixture
def organizer() -> SmartFolderOrganizer:
    return SmartFolderOrganizer()


def test_tc002_build_target_path_with_album_artist_and_album(
    organizer: SmartFolderOrganizer,
    tmp_path: Path,
) -> None:
    """TC-002: Folder path uses Album Artist at artist level and Album at album level."""
    meta = TrackMetadata(
        title="Plastic Love",
        track_artist="Mariya Takeuchi",
        album_artist="Mariya Takeuchi",
        album="VARIETY",
    )
    target = organizer.build_target_path(tmp_path, meta)
    assert target == tmp_path / "Mariya Takeuchi" / "VARIETY" / "Plastic Love.m4a"


def test_tc003_folder_uses_album_artist_not_track_artist(
    organizer: SmartFolderOrganizer,
    tmp_path: Path,
) -> None:
    """TC-003 (IR-011): When Album Artist differs from Track Artist, folder strictly uses Album Artist."""
    meta = TrackMetadata(
        title="Get Lucky",
        track_artist="Daft Punk feat. Pharrell Williams & Nile Rodgers",
        album_artist="Daft Punk",
        album="Random Access Memories",
    )
    target = organizer.build_target_path(tmp_path, meta)
    assert target.parent.parent.name == "Daft Punk"
    assert target.parent.name == "Random Access Memories"
    assert target.name == "Get Lucky.m4a"
    assert "Pharrell" not in str(target)


def test_tc011_missing_album_artist_fallback_and_unknown_artist_folder(
    organizer: SmartFolderOrganizer,
    tmp_path: Path,
) -> None:
    """TC-011 (Folder part, DEC-015):
    - If album_artist is None but track_artist exists -> fallback to track_artist.
    - If both album_artist and track_artist are None -> put in 'Unknown Artist' folder.
    """
    # Case 1: Fallback 1 -> Track Artist
    meta_fallback1 = TrackMetadata(
        title="Indie Track",
        track_artist="Solo Creator",
        album_artist=None,
        album="First EP",
    )
    target1 = organizer.build_target_path(tmp_path, meta_fallback1)
    assert target1 == tmp_path / "Solo Creator" / "First EP" / "Indie Track.m4a"

    # Case 2: Fallback 2 -> 'Unknown Artist' folder (while metadata tags remain None)
    meta_fallback2 = TrackMetadata(
        title="Mystery Song",
        track_artist=None,
        album_artist=None,
        album="Mystery Album",
    )
    target2 = organizer.build_target_path(tmp_path, meta_fallback2)
    assert target2 == tmp_path / UNKNOWN_ARTIST_FOLDER / "Mystery Album" / "Mystery Song.m4a"
    assert meta_fallback2.album_artist is None
    assert meta_fallback2.track_artist is None


def test_tc012_windows_forbidden_characters_replaced_with_underscore(
    organizer: SmartFolderOrganizer,
    tmp_path: Path,
) -> None:
    """TC-012 (DEC-014): Forbidden Windows chars \\ / : * ? \" < > | are converted to '_'."""
    meta = TrackMetadata(
        title='Song: Part 1/2 *Live* ? "Best" <Mix> | Final\\Ver',
        album_artist='AC/DC: "Rocks"',
        album="Back\\In*Black?",
    )
    target = organizer.build_target_path(tmp_path, meta)
    assert target.parent.parent.name == "AC_DC_ _Rocks_"
    assert target.parent.name == "Back_In_Black_"
    assert target.name == "Song_ Part 1_2 _Live_ _ _Best_ _Mix_ _ Final_Ver.m4a"

    # Verify folder and file can actually be created on Windows filesystem
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"test")
    assert target.exists()


def test_tc013_conflict_detection_and_keep_both_numbering(
    organizer: SmartFolderOrganizer,
    tmp_path: Path,
) -> None:
    """TC-013 (SmartFolderOrganizer part): check_conflict detects existing file and keep_both_path generates ' (1)', ' (2)'."""
    meta = TrackMetadata(
        title="Duplicate Song",
        album_artist="Artist A",
        album="Album A",
    )
    target = organizer.build_target_path(tmp_path, meta)
    assert organizer.check_conflict(target) is False

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"original")
    assert organizer.check_conflict(target) is True

    keep1 = organizer.keep_both_path(target)
    assert keep1 == target.parent / "Duplicate Song (1).m4a"
    keep1.write_bytes(b"copy 1")

    keep2 = organizer.keep_both_path(target)
    assert keep2 == target.parent / "Duplicate Song (2).m4a"


def test_tc025_trailing_dots_spaces_control_chars_and_reserved_names_on_windows(
    organizer: SmartFolderOrganizer,
    tmp_path: Path,
) -> None:
    """TC-025 (DEC-037):
    - Trailing dots/spaces all replaced with '_' ('Hello...' -> 'Hello___')
    - Reserved names before first dot appended with '_' ('CON.mix' -> 'CON_.mix', 'aux' -> 'aux_')
    - Truncation at 100 chars exposing a trailing space converts that trailing space to '_'
    - ASCII control chars 0x00-0x1F replaced with '_'
    - Actual directories and files can be created and read on Windows.
    """
    # 1. 'Hello...' -> 'Hello___'
    assert organizer.sanitize_component("Hello...") == "Hello___"
    assert organizer.sanitize_component("TrailingSpace . ") == "TrailingSpace___"

    # 2. 'CON.mix' -> 'CON_.mix', 'NUL' -> 'NUL_', 'lpt9.tar.gz' -> 'lpt9_.tar.gz'
    assert organizer.sanitize_component("CON.mix") == "CON_.mix"
    assert organizer.sanitize_component("NUL") == "NUL_"
    assert organizer.sanitize_component("lpt9.tar.gz") == "lpt9_.tar.gz"
    # Non-reserved prefix should not be touched
    assert organizer.sanitize_component("CONCERT.mix") == "CONCERT.mix"

    # 3. 100-char truncation exposing trailing spaces
    name_with_space_at_100 = ("A" * 98) + "  " + "BBBB"
    sanitized_100 = organizer.sanitize_component(name_with_space_at_100)
    assert len(sanitized_100) == MAX_COMPONENT_LENGTH
    assert sanitized_100 == ("A" * 98) + "__"
    assert not sanitized_100.endswith(" ")

    # 4. Control characters 0x00-0x1F
    control_str = "Track\x00\x07\x1b\n\r\tName"
    assert organizer.sanitize_component(control_str) == "Track______Name"

    # 5. Verify creation on actual Windows filesystem using tmp_path
    meta = TrackMetadata(
        title="CON.mix",
        album_artist="aux",
        album="Hello...",
    )
    target = organizer.build_target_path(tmp_path, meta)
    assert target == tmp_path / "aux_" / "Hello___" / "CON_.mix.m4a"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"windows_fs_check")
    assert target.exists()
    assert target.read_bytes() == b"windows_fs_check"


def test_tc026_folder_rules_unknown_album_and_multidisc_same_folder(
    organizer: SmartFolderOrganizer,
    tmp_path: Path,
) -> None:
    """TC-026 / DEC-022 (Folder rules):
    - Missing album name -> placed in 'Unknown Album' folder
    - Multi-disc album -> Disc 1 and Disc 2 share the same '<Album>' folder
    """
    meta_no_album = TrackMetadata(
        title="Single Release",
        album_artist="Artist X",
        album=None,
    )
    path_no_album = organizer.build_target_path(tmp_path, meta_no_album)
    assert path_no_album == tmp_path / "Artist X" / UNKNOWN_ALBUM_FOLDER / "Single Release.m4a"

    disc1 = TrackMetadata(
        title="Overture",
        album_artist="Symphony",
        album="Grand Collection",
        disc_number=1,
        total_discs=2,
    )
    disc2 = TrackMetadata(
        title="Finale",
        album_artist="Symphony",
        album="Grand Collection",
        disc_number=2,
        total_discs=2,
    )
    path_d1 = organizer.build_target_path(tmp_path, disc1)
    path_d2 = organizer.build_target_path(tmp_path, disc2)
    assert path_d1.parent == path_d2.parent
    assert path_d1.parent == tmp_path / "Symphony" / "Grand Collection"


def test_tc027_path_exceeding_windows_max_path_raises_err_path_too_long(
    organizer: SmartFolderOrganizer,
) -> None:
    """TC-027 (DEC-043): Full target path > 259 characters raises PathTooLongError (ERR_PATH_TOO_LONG)."""
    long_root = Path("E:\\Music")
    meta = TrackMetadata(
        title="T" * 100,
        album_artist="A" * 100,
        album="B" * 100,
    )
    with pytest.raises(PathTooLongError) as exc_info:
        organizer.build_target_path(long_root, meta)

    err = exc_info.value
    assert err.code == ErrorCode.ERR_PATH_TOO_LONG
    assert err.structured.code == ErrorCode.ERR_PATH_TOO_LONG
    assert "259" in err.message_en

    # Also test keep_both_path exceeding 259 chars when base path is exactly 258 chars
    # E:\ (3) + artist (80) + \ (1) + album (80) + \ (1) + title (89) + .m4a (4) = 258 chars
    borderline_meta = TrackMetadata(
        title="T" * 89,
        album_artist="A" * 80,
        album="B" * 80,
    )
    borderline_path = organizer.build_target_path(Path("E:\\"), borderline_meta)
    assert len(str(borderline_path)) == 258 <= WINDOWS_MAX_PATH_CHARS

    # Adding " (1)" adds 4 chars -> 262 > 259 -> raises ERR_PATH_TOO_LONG
    with pytest.raises(PathTooLongError) as exc_info_keep:
        organizer.keep_both_path(borderline_path)
    assert exc_info_keep.value.code == ErrorCode.ERR_PATH_TOO_LONG

