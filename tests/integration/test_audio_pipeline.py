"""Integration tests for AudioProcessingService and ExternalMetadataFetcher (TC-024, Plan 7.2, DEC-033, TBA-027)."""

from pathlib import Path
from typing import Any
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.real_binaries]

from pladaz.domain.enums import AudioProcessMode
from pladaz.domain.models import AudioFormat, RawTrackInfo, TrackMetadata
from pladaz.services.audio_processor import AudioProcessingService
from pladaz.services.metadata_matcher import (
    HttpExternalMetadataFetcher,
    TemporaryExactMetadataMatcher,
)
from pladaz.services.metadata_service import MetadataAlbumArtService
from pladaz.services.output_validator import OutputValidator
from pladaz.services.source_adapter import DownloadSourceAdapter


def test_tc024a_stream_with_aac_lc_uses_remux_without_reencoding_and_passes_validator(
    tmp_path: Path,
    sample_m4a_path: Path,
    sample_wide_png_bytes: bytes,
) -> None:
    """TC-024(a) (DEC-033): When an AAC (mp4a.40.2 in m4a) stream is available, system selects REMUX_AAC (-c:a copy) and output passes OutputValidator."""
    adapter = DownloadSourceAdapter(ytdlp_path=Path("yt-dlp.exe"))
    audio_proc = AudioProcessingService()
    meta_service = MetadataAlbumArtService()
    validator = OutputValidator()

    info = RawTrackInfo(
        entry_url="https://music.youtube.com/watch?v=aac_track",
        title="Remuxed AAC Track",
        artist="AAC Artist",
        album="AAC Album",
        album_artist="AAC Artist",
        track_number=1,
        disc_number=1,
        release_year="2025",
        genre="Electronic",
        thumbnail_url=None,
        audio_formats=[
            AudioFormat(format_id="140", acodec="mp4a.40.2", abr=128.0, ext="m4a"),
            AudioFormat(format_id="251", acodec="opus", abr=160.0, ext="webm"),
        ],
    )
    plan = adapter.plan_stream(info)
    assert plan.mode == AudioProcessMode.REMUX_AAC
    assert plan.format_id == "140"

    # Verify FFmpeg command arguments use -c:a copy and do NOT re-encode
    out_m4a = tmp_path / "remuxed_output.m4a"
    args = audio_proc.build_ffmpeg_args(sample_m4a_path, out_m4a, plan.mode)
    assert "-c:a" in args
    assert args[args.index("-c:a") + 1] == "copy"
    assert "-b:a" not in args

    # Run real FFmpeg remux
    result_path = audio_proc.to_m4a(sample_m4a_path, out_m4a, plan.mode)
    assert result_path.exists()

    # Tag and validate with OutputValidator
    cover_jpeg = meta_service.process_cover(sample_wide_png_bytes)
    meta = TrackMetadata(
        title="Remuxed AAC Track",
        track_artist="AAC Artist",
        album="AAC Album",
        album_artist="AAC Artist",
        cover_jpeg=cover_jpeg,
    )
    meta_service.write_m4a_tags(result_path, meta)

    val_res = validator.validate(result_path, require_cover=True)
    assert val_res.is_valid is True
    assert val_res.is_aac_lc is True
    assert val_res.has_title is True
    assert val_res.has_cover is True


def test_tc024b_stream_without_aac_encodes_to_aac_lc_without_tba027_bitrate_and_passes_validator(
    tmp_path: Path,
    sample_alac_path: Path,
    sample_wide_png_bytes: bytes,
) -> None:
    """TC-024(b) (DEC-033, TBA-027): When no AAC stream exists, system selects ENCODE_AAC_LC (-c:a aac -profile:a aac_low without -b:a) and output passes OutputValidator."""
    adapter = DownloadSourceAdapter(ytdlp_path=Path("yt-dlp.exe"))
    audio_proc = AudioProcessingService()
    meta_service = MetadataAlbumArtService()
    validator = OutputValidator()

    info = RawTrackInfo(
        entry_url="https://www.youtube.com/watch?v=opus_track",
        title="Encoded AAC Track",
        artist="Encode Artist",
        album="Encode Album",
        album_artist="Encode Artist",
        track_number=2,
        disc_number=1,
        release_year="2025",
        genre="Rock",
        thumbnail_url=None,
        audio_formats=[
            AudioFormat(format_id="249", acodec="opus", abr=50.0, ext="webm"),
            AudioFormat(format_id="251", acodec="opus", abr=160.0, ext="webm"),
        ],
    )
    plan = adapter.plan_stream(info)
    assert plan.mode == AudioProcessMode.ENCODE_AAC_LC
    assert plan.format_id == "251"

    out_m4a = tmp_path / "encoded_output.m4a"
    args = audio_proc.build_ffmpeg_args(sample_alac_path, out_m4a, plan.mode)
    assert "-c:a" in args
    assert args[args.index("-c:a") + 1] == "aac"
    assert "-profile:a" in args
    assert args[args.index("-profile:a") + 1] == "aac_low"
    # TBA-027: -b:a must NOT be set by default
    assert "-b:a" not in args

    # Run real FFmpeg encode from non-AAC (ALAC) source to AAC-LC M4A
    result_path = audio_proc.to_m4a(sample_alac_path, out_m4a, plan.mode)
    assert result_path.exists()

    cover_jpeg = meta_service.process_cover(sample_wide_png_bytes)
    meta = TrackMetadata(
        title="Encoded AAC Track",
        track_artist="Encode Artist",
        album="Encode Album",
        album_artist="Encode Artist",
        cover_jpeg=cover_jpeg,
    )
    meta_service.write_m4a_tags(result_path, meta)

    val_res = validator.validate(result_path, require_cover=True)
    assert val_res.is_valid is True
    assert val_res.is_aac_lc is True
    assert val_res.has_title is True
    assert val_res.has_cover is True


def test_itunes_and_musicbrainz_fetcher_rate_limit_and_matching() -> None:
    """Verify HttpExternalMetadataFetcher parses iTunes/MusicBrainz JSON, enforces 1 req/s on MusicBrainz, and respects TBA-026 User-Agent."""
    fake_clock = [100.0]
    sleep_calls: list[float] = []

    def clock_fn() -> float:
        return fake_clock[0]

    def sleep_fn(seconds: float) -> None:
        sleep_calls.append(seconds)
        fake_clock[0] += seconds

    captured_headers: list[dict[str, str]] = []

    def fake_http_get_json(
        url: str,
        headers: dict[str, str],
        timeout: float,
    ) -> dict[str, Any]:
        captured_headers.append(headers)
        if "itunes.apple.com" in url:
            return {
                "resultCount": 1,
                "results": [
                    {
                        "trackName": "Plastic Love",
                        "artistName": "Mariya Takeuchi",
                        "collectionName": "VARIETY",
                        "collectionArtistName": "Mariya Takeuchi",
                        "trackNumber": 2,
                        "discNumber": 1,
                        "primaryGenreName": "J-Pop",
                        "releaseDate": "1984-04-25T07:00:00Z",
                        "artworkUrl100": "https://is1-ssl.mzstatic.com/image/thumb/100x100bb.jpg",
                    }
                ],
            }
        return {
            "recordings": [
                {
                    "title": "Plastic Love",
                    "artist-credit": [{"name": "Mariya Takeuchi"}],
                    "first-release-date": "1984-04-25",
                    "releases": [
                        {
                            "title": "VARIETY",
                            "media": [{"position": 1, "track": [{"number": "2"}]}],
                        }
                    ],
                    "tags": [{"name": "City Pop"}],
                }
            ]
        }

    fetcher = HttpExternalMetadataFetcher(
        musicbrainz_user_agent="UserConfiguredAgent/1.0",
        http_get_json=fake_http_get_json,
        clock_fn=clock_fn,
        sleep_fn=sleep_fn,
    )

    # Back-to-back MusicBrainz calls only 0.3s apart -> must sleep 0.7s on second call
    mb1 = fetcher.query_musicbrainz("Plastic Love", "Mariya Takeuchi")
    assert len(mb1) == 1
    assert mb1[0].album == "VARIETY"
    assert captured_headers[-1]["User-Agent"] == "UserConfiguredAgent/1.0"

    fake_clock[0] += 0.3
    mb2 = fetcher.query_musicbrainz("Plastic Love", "Mariya Takeuchi")
    assert len(mb2) == 1
    assert len(sleep_calls) == 1
    assert pytest.approx(sleep_calls[0], rel=1e-3) == 0.7

    # Integrate with MetadataAlbumArtService + TemporaryExactMetadataMatcher
    service = MetadataAlbumArtService(
        matcher=TemporaryExactMetadataMatcher(),
        external_fetcher=fetcher,
    )
    raw = RawTrackInfo(
        entry_url="https://music.youtube.com/watch?v=plasticlove",
        title="Plastic Love",
        artist="Mariya Takeuchi",
        album=None,
        album_artist=None,
        track_number=None,
        disc_number=None,
        release_year=None,
        genre=None,
        thumbnail_url=None,
        audio_formats=[],
    )
    resolved = service.resolve_metadata(raw)
    assert resolved.album == "VARIETY"
    assert resolved.track_number == 2
    assert resolved.year == "1984"
    assert resolved.genre == "J-Pop"

