"""MetadataAlbumArtService implementation (SYSTEM_DESIGN.md 2.5(2), DEC-008, DEC-015, DEC-021, DEC-035, TBA-026)."""

from io import BytesIO
from pathlib import Path
from typing import Optional
import urllib.request

from mutagen.mp4 import MP4, MP4Cover
from PIL import Image, UnidentifiedImageError

from pladaz.domain.errors import ErrorCode, MetadataTaggingError
from pladaz.domain.interfaces import (
    ExternalMetadataFetcherProtocol,
    MetadataMatcherProtocol,
)
from pladaz.domain.models import ExternalMetadata, RawTrackInfo, TrackMetadata
from pladaz.services.logger import PladazLogger

COVER_TARGET_SIZE: tuple[int, int] = (800, 800)
COVER_JPEG_QUALITY: int = 90

# MP4 Atom keys (SYSTEM_DESIGN.md 2.5(2))
ATOM_TITLE = "\xa9nam"
ATOM_TRACK_ARTIST = "\xa9ART"  # Uppercase ART verified with mutagen.mp4
ATOM_ALBUM = "\xa9alb"
ATOM_ALBUM_ARTIST = "aART"
ATOM_TRACK_NUMBER = "trkn"
ATOM_DISC_NUMBER = "disk"
ATOM_YEAR = "\xa9day"
ATOM_GENRE = "\xa9gen"
ATOM_COVER = "covr"


def _clean_str(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    stripped = val.strip()
    return stripped if stripped else None


class MetadataAlbumArtService:
    """Resolves metadata, processes 800x800 1:1 JPEG cover art, and writes M4A atoms via mutagen."""

    def __init__(
        self,
        matcher: Optional[MetadataMatcherProtocol] = None,
        external_fetcher: Optional[ExternalMetadataFetcherProtocol] = None,
        logger: Optional[PladazLogger] = None,
    ) -> None:
        self._matcher = matcher
        self._external_fetcher = external_fetcher
        self._logger = logger

    def enrich_from_external(
        self,
        info: RawTrackInfo,
        warnings_out: Optional[list[str]] = None,
    ) -> Optional[ExternalMetadata]:
        """Query external candidates and return the first candidate matching via MetadataMatcherProtocol (DEC-035, TBA-026)."""
        if self._external_fetcher is None or self._matcher is None:
            return None

        src_title = _clean_str(info.title)
        src_artist = _clean_str(info.artist) or _clean_str(info.album_artist)
        if not src_title or not src_artist:
            return None

        try:
            candidates = self._external_fetcher.fetch_candidates(info)
        except Exception as exc:
            warn_msg = (
                f"{ErrorCode.WARN_METADATA_ENRICH_UNAVAILABLE}: "
                f"External metadata enrichment unavailable ({exc}). Leaving missing fields blank."
            )
            if warnings_out is not None:
                warnings_out.append(warn_msg)
            if self._logger:
                self._logger.warning(
                    component="MetadataAlbumArtService",
                    message=warn_msg,
                )
            return None

        for candidate in candidates:
            cand_title = _clean_str(candidate.title) or ""
            cand_artist = _clean_str(candidate.artist) or ""
            if self._matcher.is_match(src_title, src_artist, cand_title, cand_artist):
                return candidate

        return None

    def resolve_metadata(
        self,
        info: RawTrackInfo,
        warnings_out: Optional[list[str]] = None,
    ) -> TrackMetadata:
        """Resolve TrackMetadata following Plan 7.3, DEC-015, DEC-021, DEC-035."""
        title = _clean_str(info.title) or ""
        track_artist = _clean_str(info.artist)
        album = _clean_str(info.album)
        album_artist = _clean_str(info.album_artist)
        track_number = info.track_number
        disc_number = info.disc_number
        year = _clean_str(info.release_year)
        genre = _clean_str(info.genre)
        cover_url = _clean_str(info.thumbnail_url)

        needs_enrichment = any(
            field is None
            for field in (
                album_artist,
                album,
                track_number,
                disc_number,
                genre,
                year,
                cover_url,
            )
        )

        if needs_enrichment:
            ext = self.enrich_from_external(info, warnings_out=warnings_out)
            if ext is not None:
                if track_artist is None:
                    track_artist = _clean_str(ext.artist)
                if album is None:
                    album = _clean_str(ext.album)
                if album_artist is None:
                    album_artist = _clean_str(ext.album_artist)
                if track_number is None:
                    track_number = ext.track_number
                if disc_number is None:
                    disc_number = ext.disc_number
                if year is None:
                    year = _clean_str(ext.year)
                if genre is None:
                    genre = _clean_str(ext.genre)
                if cover_url is None:
                    cover_url = _clean_str(ext.cover_url)

        # Apply DEC-015 / Plan 7.3 Album Artist fallback rule:
        # 1. Use album_artist if available
        # 2. Fallback 1: Use track_artist
        # 3. Fallback 2: None (leave empty in tags; NEVER write 'Unknown Artist' into metadata tags)
        if album_artist is None:
            album_artist = track_artist

        cover_jpeg: Optional[bytes] = None
        if cover_url:
            raw_cover: Optional[bytes] = None
            if self._external_fetcher is not None:
                try:
                    raw_cover = self._external_fetcher.fetch_cover_bytes(cover_url)
                except Exception as exc:
                    if self._logger:
                        self._logger.warning(
                            component="MetadataAlbumArtService",
                            message=f"Cover fetch failed via external fetcher: {exc}",
                        )
            else:
                try:
                    req = urllib.request.Request(
                        cover_url,
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PLADAZ/1.0"},
                    )
                    with urllib.request.urlopen(req, timeout=10.0) as resp:
                        raw_cover = resp.read()
                except Exception as exc:
                    if self._logger:
                        self._logger.warning(
                            component="MetadataAlbumArtService",
                            message=f"Direct cover fetch failed: {exc}",
                        )

            if raw_cover:
                try:
                    cover_jpeg = self.process_cover(raw_cover)
                except Exception as exc:
                    if self._logger:
                        self._logger.warning(
                            component="MetadataAlbumArtService",
                            message=f"Cover process failed: {exc}",
                        )

        return TrackMetadata(
            title=title,
            track_artist=track_artist,
            album=album,
            album_artist=album_artist,
            track_number=track_number,
            total_tracks=None,
            disc_number=disc_number,
            total_discs=None,
            year=year,
            genre=genre,
            cover_jpeg=cover_jpeg,
        )

    def process_cover(self, image_bytes: bytes) -> bytes:
        """Convert raw image bytes to RGB, center-crop to 1:1 square, resize to 800x800 JPEG (DEC-021)."""
        if not image_bytes:
            raise MetadataTaggingError(
                message_en="Cannot process empty image bytes for album cover.",
                details="image_bytes is empty",
            )
        try:
            with Image.open(BytesIO(image_bytes)) as img:
                rgb_img = img.convert("RGB")
                width, height = rgb_img.size
                if width <= 0 or height <= 0:
                    raise ValueError("Invalid image dimensions.")

                side = min(width, height)
                left = (width - side) // 2
                top = (height - side) // 2
                right = left + side
                bottom = top + side

                cropped = rgb_img.crop((left, top, right, bottom))
                resized = cropped.resize(COVER_TARGET_SIZE, Image.Resampling.LANCZOS)

                out_buf = BytesIO()
                resized.save(out_buf, format="JPEG", quality=COVER_JPEG_QUALITY)
                return out_buf.getvalue()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise MetadataTaggingError(
                message_en="Failed to process album art image into 800x800 JPEG.",
                details=str(exc),
            ) from exc

    def write_m4a_tags(self, path: Path, meta: TrackMetadata) -> None:
        """Write 9 metadata fields and cover art into an M4A container using mutagen.mp4 (DEC-008, Plan 7.3)."""
        title_clean = _clean_str(meta.title)
        if not title_clean:
            raise MetadataTaggingError(
                message_en="Cannot write M4A tags: Title is required (DEC-030).",
                details="meta.title is empty",
            )

        try:
            mp4 = MP4(path)
            if mp4.tags is None:
                mp4.add_tags()
            tags = mp4.tags
            assert tags is not None

            # 1. Title (required, DEC-030)
            tags[ATOM_TITLE] = [title_clean]

            # 2. Track Artist (©ART uppercase)
            track_artist = _clean_str(meta.track_artist)
            if track_artist is not None:
                tags[ATOM_TRACK_ARTIST] = [track_artist]
            else:
                tags.pop(ATOM_TRACK_ARTIST, None)

            # 3. Album (©alb)
            album = _clean_str(meta.album)
            if album is not None:
                tags[ATOM_ALBUM] = [album]
            else:
                tags.pop(ATOM_ALBUM, None)

            # 4. Album Artist (aART, with fallback to track_artist if not already resolved)
            album_artist = _clean_str(meta.album_artist) or track_artist
            if album_artist is not None:
                tags[ATOM_ALBUM_ARTIST] = [album_artist]
            else:
                tags.pop(ATOM_ALBUM_ARTIST, None)

            # 5. Track Number (trkn)
            if meta.track_number is not None:
                tags[ATOM_TRACK_NUMBER] = [(int(meta.track_number), int(meta.total_tracks or 0))]
            else:
                tags.pop(ATOM_TRACK_NUMBER, None)

            # 6. Disc Number (disk)
            if meta.disc_number is not None:
                tags[ATOM_DISC_NUMBER] = [(int(meta.disc_number), int(meta.total_discs or 0))]
            else:
                tags.pop(ATOM_DISC_NUMBER, None)

            # 7. Year (©day)
            year = _clean_str(meta.year)
            if year is not None:
                tags[ATOM_YEAR] = [year]
            else:
                tags.pop(ATOM_YEAR, None)

            # 8. Genre (©gen)
            genre = _clean_str(meta.genre)
            if genre is not None:
                tags[ATOM_GENRE] = [genre]
            else:
                tags.pop(ATOM_GENRE, None)

            # 9. Album Art (covr)
            if meta.cover_jpeg is not None:
                tags[ATOM_COVER] = [
                    MP4Cover(meta.cover_jpeg, imageformat=MP4Cover.FORMAT_JPEG)
                ]
            else:
                tags.pop(ATOM_COVER, None)

            mp4.save()
        except MetadataTaggingError:
            raise
        except Exception as exc:
            raise MetadataTaggingError(
                message_en=f"Failed to write M4A tags to '{Path(path).name}'.",
                details=str(exc),
            ) from exc

