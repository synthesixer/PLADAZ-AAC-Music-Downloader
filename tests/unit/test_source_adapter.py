"""Unit tests for DownloadSourceAdapter (URL validation, JSON parsing, stream planning, cancellation, and TC-031 yt-dlp update)."""

from pathlib import Path
from threading import Event
import pytest

from pladaz.domain.enums import AudioProcessMode
from pladaz.domain.errors import (
    ErrorCode,
    SourceExtractionError,
    SourceInvalidUrlError,
    TaskCancelledError,
)
from pladaz.domain.models import AudioFormat, RawTrackInfo, StreamPlan
from pladaz.services.source_adapter import (
    DownloadSourceAdapter,
    parse_flat_entries,
    parse_track_info,
    validate_youtube_url,
)


def _create_fake_ytdlp_bat(
    folder: Path,
    name: str = "yt-dlp.bat",
    version: str = "2026.01.01",
    broken: bool = False,
) -> Path:
    """Create a lightweight Windows .bat script simulating yt-dlp.exe for subprocess tests."""
    bat_path = folder / name
    if broken:
        bat_path.write_text("@echo off\r\nexit /b 1\r\n", encoding="utf-8")
    else:
        bat_path.write_text(
            f'@echo off\r\nif "%~1"=="--version" (\r\n  echo {version}\r\n  exit /b 0\r\n)\r\nexit /b 0\r\n',
            encoding="utf-8",
        )
    return bat_path


def test_validate_youtube_url_accepts_youtube_and_ytmusic_and_rejects_others() -> None:
    """Verify URL validation accepts YouTube / YT Music links and rejects non-YouTube URLs with ERR_SOURCE_INVALID_URL."""
    assert (
        validate_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )
    assert (
        validate_youtube_url("https://music.youtube.com/watch?v=abc123&list=RDAMVM")
        == "https://music.youtube.com/watch?v=abc123&list=RDAMVM"
    )
    assert (
        validate_youtube_url("https://youtu.be/dQw4w9WgXcQ")
        == "https://youtu.be/dQw4w9WgXcQ"
    )

    for bad_url in [
        "",
        "not-a-url",
        "ftp://www.youtube.com/watch?v=123",
        "https://open.spotify.com/track/12345",
        "https://soundcloud.com/artist/track",
        "https://www.youtube.com/",
    ]:
        with pytest.raises(SourceInvalidUrlError) as exc_info:
            validate_youtube_url(bad_url)
        assert exc_info.value.code == ErrorCode.ERR_SOURCE_INVALID_URL


def test_parse_flat_entries_single_and_playlist() -> None:
    """Verify flat JSON parsing handles both single tracks and playlists/albums."""
    single_json = {
        "id": "vid1",
        "title": "Single Song",
        "webpage_url": "https://www.youtube.com/watch?v=vid1",
    }
    single_entries = parse_flat_entries(
        single_json, "https://www.youtube.com/watch?v=vid1", batch_id="batch-1"
    )
    assert len(single_entries) == 1
    assert single_entries[0].entry_url == "https://www.youtube.com/watch?v=vid1"
    assert single_entries[0].title_hint == "Single Song"
    assert single_entries[0].batch_id == "batch-1"

    playlist_json = {
        "_type": "playlist",
        "id": "PL123",
        "entries": [
            {"id": "t1", "title": "Track 1"},
            {"id": "t2", "title": "Track 2", "url": "https://music.youtube.com/watch?v=t2"},
        ],
    }
    pl_entries = parse_flat_entries(
        playlist_json,
        "https://music.youtube.com/playlist?list=PL123",
        batch_id="batch-pl",
    )
    assert len(pl_entries) == 2
    assert pl_entries[0].entry_url == "https://www.youtube.com/watch?v=t1"
    assert pl_entries[0].index_in_batch == 0
    assert pl_entries[1].entry_url == "https://music.youtube.com/watch?v=t2"
    assert pl_entries[1].index_in_batch == 1


def test_parse_track_info_and_plan_stream_dec033() -> None:
    """Verify parse_track_info and plan_stream select REMUX_AAC when mp4a.40.2 m4a exists, else ENCODE_AAC_LC (DEC-033)."""
    raw_json = {
        "title": "Video Title",
        "track": "Official Track Name",
        "artist": "Track Artist",
        "album": "Album Name",
        "album_artist": "Album Artist",
        "track_number": 4,
        "disc_number": 1,
        "release_date": "20240512",
        "genre": "J-Pop",
        "thumbnail": "https://i.ytimg.com/vi/xxx/maxresdefault.jpg",
        "formats": [
            {"format_id": "249", "acodec": "opus", "abr": 50.0, "ext": "webm"},
            {"format_id": "140", "acodec": "mp4a.40.2", "abr": 129.5, "ext": "m4a"},
            {"format_id": "251", "acodec": "opus", "abr": 160.0, "ext": "webm"},
        ],
    }
    info = parse_track_info(raw_json, "https://music.youtube.com/watch?v=xxx")
    assert info.title == "Official Track Name"
    assert info.artist == "Track Artist"
    assert info.release_year == "2024"
    assert len(info.audio_formats) == 3

    adapter = DownloadSourceAdapter(ytdlp_path=Path("yt-dlp.exe"))
    # Even though opus (251) has 160 kbps, DEC-033 mandates preferring AAC (mp4a.40.2 in m4a) for remux!
    plan_aac = adapter.plan_stream(info)
    assert plan_aac.format_id == "140"
    assert plan_aac.mode == AudioProcessMode.REMUX_AAC

    # When no mp4a.40.2 m4a stream is available, pick highest abr for ENCODE_AAC_LC
    info_opus_only = RawTrackInfo(
        entry_url="https://music.youtube.com/watch?v=yyy",
        title="Opus Track",
        artist="Artist",
        album=None,
        album_artist=None,
        track_number=None,
        disc_number=None,
        release_year=None,
        genre=None,
        thumbnail_url=None,
        audio_formats=[
            AudioFormat(format_id="249", acodec="opus", abr=50.0, ext="webm"),
            AudioFormat(format_id="251", acodec="opus", abr=160.0, ext="webm"),
        ],
    )
    plan_enc = adapter.plan_stream(info_opus_only)
    assert plan_enc.format_id == "251"
    assert plan_enc.mode == AudioProcessMode.ENCODE_AAC_LC


def test_download_stream_pre_cancelled_raises_err_task_cancelled(tmp_path: Path) -> None:
    """Verify download_stream immediately raises TaskCancelledError (ERR_TASK_CANCELLED) if cancel_event is set."""
    fake_bin = _create_fake_ytdlp_bat(tmp_path)
    adapter = DownloadSourceAdapter(ytdlp_path=fake_bin)
    cancel_ev = Event()
    cancel_ev.set()

    with pytest.raises(TaskCancelledError) as exc_info:
        adapter.download_stream(
            entry_url="https://www.youtube.com/watch?v=abc",
            plan=StreamPlan(format_id="140", mode=AudioProcessMode.REMUX_AAC),
            temp_dir=tmp_path / "dl",
            cancel_event=cancel_ev,
        )
    assert exc_info.value.code == ErrorCode.ERR_TASK_CANCELLED
    assert exc_info.value.recoverable is True


def test_tc031_update_ytdlp_success_and_failure_rollback(tmp_path: Path) -> None:
    """TC-031 (DEC-026, DEC-038):
    (a) Successful update replaces yt-dlp binary and returns old_version -> new_version.
    (b) Failed update (network error or corrupt binary) keeps original yt-dlp intact and returns success=False.
    """
    bin_path = _create_fake_ytdlp_bat(tmp_path, name="yt-dlp.bat", version="2025.12.01")
    original_content = bin_path.read_text(encoding="utf-8")

    # (a) Successful update
    def download_valid_new_binary(url: str, dest: Path) -> None:
        _create_fake_ytdlp_bat(dest.parent, name=dest.name, version="2026.10.21")

    adapter_ok = DownloadSourceAdapter(
        ytdlp_path=bin_path,
        binary_downloader=download_valid_new_binary,
    )
    res_ok = adapter_ok.update_ytdlp()
    assert res_ok.success is True
    assert res_ok.old_version == "2025.12.01"
    assert res_ok.new_version == "2026.10.21"
    assert adapter_ok.get_version() == "2026.10.21"
    assert not (tmp_path / "yt-dlp.tmp.bat").exists()

    # (b1) Failed update due to network error -> keeps 2026.10.21 intact
    def download_network_error(url: str, dest: Path) -> None:
        raise OSError("Simulated network failure")

    adapter_net_fail = DownloadSourceAdapter(
        ytdlp_path=bin_path,
        binary_downloader=download_network_error,
    )
    res_net_fail = adapter_net_fail.update_ytdlp()
    assert res_net_fail.success is False
    assert res_net_fail.old_version == "2026.10.21"
    assert res_net_fail.new_version is None
    assert adapter_net_fail.get_version() == "2026.10.21"

    # (b2) Failed update due to broken binary failing --version -> keeps 2026.10.21 intact
    def download_broken_binary(url: str, dest: Path) -> None:
        _create_fake_ytdlp_bat(dest.parent, name=dest.name, broken=True)

    adapter_broken = DownloadSourceAdapter(
        ytdlp_path=bin_path,
        binary_downloader=download_broken_binary,
    )
    res_broken = adapter_broken.update_ytdlp()
    assert res_broken.success is False
    assert res_broken.old_version == "2026.10.21"
    assert adapter_broken.get_version() == "2026.10.21"
    assert not (tmp_path / "yt-dlp.tmp.bat").exists()
