"""Domain protocols (interfaces) for Dependency Inversion (SYSTEM_DESIGN.md 1.2 & 2.4)."""

from pathlib import Path
from typing import Optional, Protocol

from pladaz.domain.models import ExternalMetadata, RawTrackInfo, SDCardStatus


class MetadataMatcherProtocol(Protocol):
    """Protocol for TBA-026: matching candidate external metadata with source title/artist (DEC-035).

    Because TBA-026 (exact matching rules for title/artist comparison) remains TBA,
    the core system depends only on this Protocol.
    """

    def is_match(
        self,
        src_title: str,
        src_artist: str,
        cand_title: str,
        cand_artist: str,
    ) -> bool:
        """Return True if candidate title AND artist match source title AND artist."""
        ...


class ExternalMetadataFetcherProtocol(Protocol):
    """Protocol for fetching external metadata candidates and cover bytes without network coupling in Phase 2."""

    def fetch_candidates(self, info: RawTrackInfo) -> list[ExternalMetadata]:
        """Return external metadata candidates for the given track info."""
        ...

    def fetch_cover_bytes(self, url: str) -> Optional[bytes]:
        """Return raw image bytes from a cover URL, or None if unavailable."""
        ...


class DriveProbeProtocol(Protocol):
    """Protocol abstracting OS/Win32 drive inspection and low-level file copying for SDCardManager."""

    def list_removable_drives(self) -> list[SDCardStatus]:
        """Return all currently connected removable drives."""
        ...

    def probe_destination(self, dest: Path) -> SDCardStatus:
        """Inspect the drive and directory status for the given destination path."""
        ...

    def copy_file_with_fsync(self, src: Path, dst: Path) -> None:
        """Copy src to dst in chunks and call flush() + os.fsync() before closing."""
        ...

