"""External metadata client (iTunes / MusicBrainz) and TemporaryExactMetadataMatcher stub for TBA-026 (Plan 7.2, DEC-021, DEC-035, TBA-026)."""

import json
from threading import Lock
import time
from typing import Any, Callable, Optional
from urllib.parse import urlencode
import urllib.request

from pladaz.domain.interfaces import (
    ExternalMetadataFetcherProtocol,
    MetadataMatcherProtocol,
)
from pladaz.domain.models import ExternalMetadata, RawTrackInfo
from pladaz.services.logger import PladazLogger

ITUNES_SEARCH_URL: str = "https://itunes.apple.com/search"
MUSICBRAINZ_RECORDING_URL: str = "https://musicbrainz.org/ws/2/recording"

# Plan 7.2: MusicBrainz rate limit is strictly at most 1 request per second
MUSICBRAINZ_MIN_INTERVAL_SEC: float = 1.0

DEFAULT_HTTP_TIMEOUT_SEC: float = 10.0

HttpGetJsonFn = Callable[[str, dict[str, str], float], dict[str, Any]]
HttpGetBytesFn = Callable[[str, dict[str, str], float], bytes]


class TemporaryExactMetadataMatcher(MetadataMatcherProtocol):
    """[TEMPORARY STUB FOR TBA-026] Simple exact string matcher after .strip().

    NOTE: Detailed comparison rules for title/artist matching (case sensitivity, 'feat.',
    '(Official Video)', etc.) remain TBA-026 in IMPLEMENT_PLAN.md. This stub performs strict
    exact equality after trimming whitespace so the pipeline can run without guessing TBA-026.
    """

    def is_match(
        self,
        src_title: str,
        src_artist: str,
        cand_title: str,
        cand_artist: str,
    ) -> bool:
        s_t = (src_title or "").strip()
        s_a = (src_artist or "").strip()
        c_t = (cand_title or "").strip()
        c_a = (cand_artist or "").strip()
        if not s_t or not s_a or not c_t or not c_a:
            return False
        return (s_t == c_t) and (s_a == c_a)


def _default_http_get_json(
    url: str,
    headers: dict[str, str],
    timeout_sec: float,
) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("Expected JSON object from metadata API.")
        return parsed


def _default_http_get_bytes(
    url: str,
    headers: dict[str, str],
    timeout_sec: float,
) -> bytes:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        return resp.read()


def _safe_int(val: Any) -> Optional[int]:
    if val is None or isinstance(val, bool):
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def parse_itunes_results(payload: dict[str, Any]) -> list[ExternalMetadata]:
    """Parse iTunes Search API JSON response into ExternalMetadata items."""
    items = payload.get("results")
    if not isinstance(items, list):
        return []
    candidates: list[ExternalMetadata] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = item.get("trackName")
        artist = item.get("artistName")
        if not title or not artist:
            continue
        release_date = item.get("releaseDate")
        year = (
            str(release_date).strip()[:4]
            if isinstance(release_date, str)
            and len(release_date.strip()) >= 4
            and release_date.strip()[:4].isdigit()
            else None
        )
        artwork_url = item.get("artworkUrl100")
        high_res_cover = (
            str(artwork_url).replace("100x100bb", "1000x1000bb")
            if isinstance(artwork_url, str) and artwork_url.strip()
            else None
        )
        candidates.append(
            ExternalMetadata(
                source="itunes",
                title=str(title).strip(),
                artist=str(artist).strip(),
                album=(
                    str(item["collectionName"]).strip()
                    if item.get("collectionName")
                    else None
                ),
                album_artist=(
                    str(item["collectionArtistName"]).strip()
                    if item.get("collectionArtistName")
                    else str(artist).strip()
                ),
                track_number=_safe_int(item.get("trackNumber")),
                disc_number=_safe_int(item.get("discNumber")),
                genre=(
                    str(item["primaryGenreName"]).strip()
                    if item.get("primaryGenreName")
                    else None
                ),
                year=year,
                cover_url=high_res_cover,
            )
        )
    return candidates


def parse_musicbrainz_results(payload: dict[str, Any]) -> list[ExternalMetadata]:
    """Parse MusicBrainz recording search JSON response into ExternalMetadata items."""
    recordings = payload.get("recordings")
    if not isinstance(recordings, list):
        return []
    candidates: list[ExternalMetadata] = []
    for rec in recordings:
        if not isinstance(rec, dict):
            continue
        title = rec.get("title")
        artist_credit = rec.get("artist-credit")
        artist_name: Optional[str] = None
        if isinstance(artist_credit, list) and artist_credit:
            first_credit = artist_credit[0]
            if isinstance(first_credit, dict):
                artist_name = first_credit.get("name") or (
                    first_credit.get("artist", {}).get("name")
                    if isinstance(first_credit.get("artist"), dict)
                    else None
                )
        if not title or not artist_name:
            continue

        album: Optional[str] = None
        album_artist: Optional[str] = str(artist_name).strip()
        track_number: Optional[int] = None
        disc_number: Optional[int] = None
        year: Optional[str] = None

        first_release_date = rec.get("first-release-date")
        if (
            isinstance(first_release_date, str)
            and len(first_release_date.strip()) >= 4
            and first_release_date.strip()[:4].isdigit()
        ):
            year = first_release_date.strip()[:4]

        releases = rec.get("releases")
        if isinstance(releases, list) and releases:
            rel = releases[0]
            if isinstance(rel, dict):
                if rel.get("title"):
                    album = str(rel["title"]).strip()
                if not year and isinstance(rel.get("date"), str) and len(rel["date"].strip()) >= 4:
                    if rel["date"].strip()[:4].isdigit():
                        year = rel["date"].strip()[:4]
                media_list = rel.get("media")
                if isinstance(media_list, list) and media_list:
                    med = media_list[0]
                    if isinstance(med, dict):
                        disc_number = _safe_int(med.get("position"))
                        track_list = med.get("track")
                        if isinstance(track_list, list) and track_list:
                            trk = track_list[0]
                            if isinstance(trk, dict):
                                track_number = _safe_int(trk.get("number"))

        genre: Optional[str] = None
        tags = rec.get("tags")
        if isinstance(tags, list) and tags:
            first_tag = tags[0]
            if isinstance(first_tag, dict) and first_tag.get("name"):
                genre = str(first_tag["name"]).strip()

        candidates.append(
            ExternalMetadata(
                source="musicbrainz",
                title=str(title).strip(),
                artist=str(artist_name).strip(),
                album=album,
                album_artist=album_artist,
                track_number=track_number,
                disc_number=disc_number,
                genre=genre,
                year=year,
                cover_url=None,
            )
        )
    return candidates


class HttpExternalMetadataFetcher(ExternalMetadataFetcherProtocol):
    """HTTP client querying iTunes Search API and MusicBrainz API (with 1 req/s rate limit and TBA-026 User-Agent)."""

    def __init__(
        self,
        # TBA-026: User-Agent for MusicBrainz must be provided by user/config; never fabricate developer contact info
        musicbrainz_user_agent: Optional[str] = None,
        timeout_sec: float = DEFAULT_HTTP_TIMEOUT_SEC,
        mb_min_interval_sec: float = MUSICBRAINZ_MIN_INTERVAL_SEC,
        http_get_json: Optional[HttpGetJsonFn] = None,
        http_get_bytes: Optional[HttpGetBytesFn] = None,
        logger: Optional[PladazLogger] = None,
        clock_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.musicbrainz_user_agent = (
            musicbrainz_user_agent.strip()
            if musicbrainz_user_agent and musicbrainz_user_agent.strip()
            else None
        )
        self.timeout_sec = timeout_sec
        self.mb_min_interval_sec = mb_min_interval_sec
        self._http_get_json: HttpGetJsonFn = http_get_json or _default_http_get_json
        self._http_get_bytes: HttpGetBytesFn = http_get_bytes or _default_http_get_bytes
        self._logger = logger
        self._clock_fn = clock_fn
        self._sleep_fn = sleep_fn
        self._mb_lock = Lock()
        self._last_mb_request_ts: Optional[float] = None

    def _wait_musicbrainz_rate_limit(self) -> None:
        """Ensure at least `mb_min_interval_sec` (1.0s) between MusicBrainz API calls (Plan 7.2)."""
        with self._mb_lock:
            now = self._clock_fn()
            if self._last_mb_request_ts is not None:
                elapsed = now - self._last_mb_request_ts
                if elapsed < self.mb_min_interval_sec:
                    wait_sec = self.mb_min_interval_sec - elapsed
                    self._sleep_fn(wait_sec)
            self._last_mb_request_ts = self._clock_fn()

    def query_itunes(self, title: str, artist: str) -> list[ExternalMetadata]:
        """Query iTunes Search API (no rate limit restriction per SYSTEM_DESIGN.md 1.1)."""
        params = urlencode(
            {
                "term": f"{artist} {title}",
                "media": "music",
                "entity": "song",
                "limit": "5",
            }
        )
        url = f"{ITUNES_SEARCH_URL}?{params}"
        payload = self._http_get_json(
            url,
            {"Accept": "application/json"},
            self.timeout_sec,
        )
        return parse_itunes_results(payload)

    def query_musicbrainz(self, title: str, artist: str) -> list[ExternalMetadata]:
        """Query MusicBrainz API enforcing 1 req/s rate limit and user-configured User-Agent (TBA-026)."""
        if not self.musicbrainz_user_agent:
            if self._logger:
                self._logger.warning(
                    component="HttpExternalMetadataFetcher",
                    message=(
                        "Skipping MusicBrainz query because musicbrainz_user_agent is not configured (TBA-026)."
                    ),
                )
            return []

        self._wait_musicbrainz_rate_limit()
        lucene_query = f'recording:"{title}" AND artist:"{artist}"'
        params = urlencode({"query": lucene_query, "fmt": "json", "limit": "5"})
        url = f"{MUSICBRAINZ_RECORDING_URL}?{params}"
        headers = {
            "User-Agent": self.musicbrainz_user_agent,
            "Accept": "application/json",
        }
        payload = self._http_get_json(url, headers, self.timeout_sec)
        return parse_musicbrainz_results(payload)

    def fetch_candidates(self, info: RawTrackInfo) -> list[ExternalMetadata]:
        """Fetch candidates from iTunes and MusicBrainz. Raises if all attempted queries fail with network errors."""
        title = (info.title or "").strip()
        artist = (info.artist or info.album_artist or "").strip()
        if not title or not artist:
            return []

        candidates: list[ExternalMetadata] = []
        itunes_error: Optional[Exception] = None
        mb_error: Optional[Exception] = None

        try:
            candidates.extend(self.query_itunes(title, artist))
        except Exception as exc:
            itunes_error = exc
            if self._logger:
                self._logger.warning(
                    component="HttpExternalMetadataFetcher",
                    message=f"iTunes Search API request failed: {exc}",
                )

        if self.musicbrainz_user_agent:
            try:
                candidates.extend(self.query_musicbrainz(title, artist))
            except Exception as exc:
                mb_error = exc
                if self._logger:
                    self._logger.warning(
                        component="HttpExternalMetadataFetcher",
                        message=f"MusicBrainz API request failed: {exc}",
                    )

        # If iTunes failed and either MusicBrainz was not configured or also failed, propagate exception
        # so MetadataAlbumArtService records WARN_METADATA_ENRICH_UNAVAILABLE
        if itunes_error is not None and (
            not self.musicbrainz_user_agent or mb_error is not None
        ):
            raise itunes_error

        return candidates

    def fetch_cover_bytes(self, url: str) -> Optional[bytes]:
        if not url or not url.strip():
            return None
        return self._http_get_bytes(url.strip(), {}, self.timeout_sec)

