"""SmartFolderOrganizer service (SYSTEM_DESIGN.md 2.5(3), IR-010, IR-011, IR-018, DEC-014..043)."""

from pathlib import Path
import re

from pladaz.domain.errors import PathTooLongError
from pladaz.domain.models import TrackMetadata

# Windows MAX_PATH is 260 including the terminating NUL character, so max usable path length is 259 (DEC-043).
WINDOWS_MAX_PATH_CHARS: int = 259

# Maximum characters per folder/file name component before extension (DEC-022).
MAX_COMPONENT_LENGTH: int = 100

# Default fallback folder names when metadata is missing (DEC-015, DEC-022).
UNKNOWN_ARTIST_FOLDER: str = "Unknown Artist"
UNKNOWN_ALBUM_FOLDER: str = "Unknown Album"

# Forbidden Windows characters: \ / : * ? " < > | and ASCII control chars 0x00-0x1F (DEC-014, DEC-034, DEC-037)
_FORBIDDEN_CHARS_RE: re.Pattern[str] = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

# Trailing dots and spaces at the end of a component name (DEC-037)
_TRAILING_DOTS_SPACES_RE: re.Pattern[str] = re.compile(r"[. ]+$")

# Windows reserved device names (case-insensitive, checked on stem before first dot per DEC-037)
_WINDOWS_RESERVED_NAMES: frozenset[str] = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)


def _replace_trailing_dots_and_spaces(text: str) -> str:
    """Replace every trailing dot (.) or space ( ) at the end of text with '_' (DEC-037)."""
    match = _TRAILING_DOTS_SPACES_RE.search(text)
    if not match:
        return text
    trailing_len = len(match.group(0))
    return text[:-trailing_len] + ("_" * trailing_len)


class SmartFolderOrganizer:
    """Organizes target folder and file paths on Micro SD Card according to PLADAZ rules."""

    def sanitize_component(
        self,
        name: str,
        max_length: int = MAX_COMPONENT_LENGTH,
    ) -> str:
        """Sanitize a single folder or file stem component in 4 strict steps (DEC-037).

        1. Replace Windows forbidden characters (\\ / : * ? " < > |) and ASCII 0x00-0x1F with '_'.
        2. Truncate to at most `max_length` (100) characters.
        3. Replace all trailing dots (.) and spaces ( ) with '_' character-for-character.
        4. Check Windows reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9) case-insensitively
           against the part before the first dot; if matched, append '_' to that part.
        """
        # Step 1: Forbidden & control characters -> '_'
        step1 = _FORBIDDEN_CHARS_RE.sub("_", name)

        # Step 2: Truncate to max_length (100) characters
        step2 = step1[:max_length]

        # Step 3: Trailing dots/spaces -> '_' (after truncation so newly exposed trailing spaces/dots are caught)
        step3 = _replace_trailing_dots_and_spaces(step2)

        # Step 4: Reserved device name check on the stem before the first dot
        parts = step3.split(".", 1)
        first_part = parts[0]
        if first_part.upper() in _WINDOWS_RESERVED_NAMES:
            first_part = f"{first_part}_"
            step4 = f"{first_part}.{parts[1]}" if len(parts) > 1 else first_part
        else:
            step4 = step3

        # Ensure final length still respects max_length and has no trailing dots/spaces
        if len(step4) > max_length:
            step4 = _replace_trailing_dots_and_spaces(step4[:max_length])

        return step4

    def resolve_folder_names(self, meta: TrackMetadata) -> tuple[str, str]:
        """Resolve (artist_folder, album_folder) per IR-011, DEC-004, DEC-015, DEC-022.

        - Artist folder uses `album_artist` first; if empty/None, falls back to `track_artist`;
          if both are empty/None, uses 'Unknown Artist' (DEC-015).
        - Album folder uses `album`; if empty/None, uses 'Unknown Album' (DEC-022).
        - Multi-disc albums share the same `<Album>` folder (DEC-022).
        """
        raw_artist = (
            meta.album_artist
            if (meta.album_artist and meta.album_artist.strip())
            else (
                meta.track_artist
                if (meta.track_artist and meta.track_artist.strip())
                else None
            )
        )
        if raw_artist is None:
            artist_folder = UNKNOWN_ARTIST_FOLDER
        else:
            artist_folder = self.sanitize_component(raw_artist.strip())
            if not artist_folder:
                artist_folder = UNKNOWN_ARTIST_FOLDER

        raw_album = meta.album if (meta.album and meta.album.strip()) else None
        if raw_album is None:
            album_folder = UNKNOWN_ALBUM_FOLDER
        else:
            album_folder = self.sanitize_component(raw_album.strip())
            if not album_folder:
                album_folder = UNKNOWN_ALBUM_FOLDER

        return artist_folder, album_folder

    def build_target_path(self, dest_root: Path, meta: TrackMetadata) -> Path:
        """Build `<dest_root>/<Album Artist>/<Album>/<Title>.m4a` and enforce Windows MAX_PATH (DEC-016, DEC-043)."""
        if not meta.title or not meta.title.strip():
            raise ValueError("TrackMetadata.title is required to build target path.")

        artist_folder, album_folder = self.resolve_folder_names(meta)
        title_stem = self.sanitize_component(meta.title.strip())
        if not title_stem:
            title_stem = "_"

        target_path = Path(dest_root) / artist_folder / album_folder / f"{title_stem}.m4a"
        self._check_max_path(target_path)
        return target_path

    def check_conflict(self, target: Path) -> bool:
        """Return True if a file already exists at `target` (DEC-019, DEC-036)."""
        return Path(target).exists()

    def keep_both_path(self, target: Path) -> Path:
        """Find the next available `<Title> (1).m4a`, `<Title> (2).m4a`, ... path (DEC-019, DEC-043)."""
        target_path = Path(target)
        parent = target_path.parent
        suffix = target_path.suffix or ".m4a"
        stem = target_path.stem

        counter = 1
        while True:
            candidate = parent / f"{stem} ({counter}){suffix}"
            self._check_max_path(candidate)
            if not candidate.exists():
                return candidate
            counter += 1

    @staticmethod
    def _check_max_path(path: Path) -> None:
        """Raise PathTooLongError (ERR_PATH_TOO_LONG) if the full path exceeds 259 chars (DEC-043)."""
        path_str = str(path)
        if len(path_str) > WINDOWS_MAX_PATH_CHARS:
            raise PathTooLongError(
                message_en=(
                    f"Target path length ({len(path_str)} characters) exceeds the Windows limit "
                    f"of {WINDOWS_MAX_PATH_CHARS} characters. Artist, album, or track title is too long."
                ),
                details=f"path_length={len(path_str)}, max={WINDOWS_MAX_PATH_CHARS}",
            )

