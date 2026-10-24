"""Regression tests for gaps found when reviewing Browser Authentication (DEC-052) against the 2026-10-24 spec."""

from pathlib import Path
import sqlite3
import subprocess
import pytest

pytestmark = pytest.mark.unit

from pladaz.domain.errors import BrowserCookiesError, SourceExtractionError
from pladaz.services.browser_auth import (
    BROWSER_LABELS,
    CHECK_FAILED,
    CHECK_PROFILE_NOT_FOUND,
    CHECK_READABLE,
    classify_cookie_store_error,
    parse_cookie_check_output,
)
from pladaz.services.logger import PladazLogger
from pladaz.services.source_adapter import DownloadSourceAdapter
from tests.integration.test_audit_fixes import _bridge

ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")

# yt-dlp prints these lines on every run that uses --cookies-from-browser, even when the cookies were read fine.
COOKIES_READ_OK = "Extracting cookies from firefox\nExtracted 912 cookies from firefox\n"


def test_unrelated_failure_after_cookies_were_read_is_not_a_cookie_error() -> None:
    assert classify_cookie_store_error(COOKIES_READ_OK + "ERROR: [youtube] abc123: Video unavailable") is None
    partly = "Extracting cookies from chrome\nExtracted 500 cookies from chrome (3 could not be decrypted)\n"
    assert classify_cookie_store_error(partly + "ERROR: [youtube] abc123: This video is not available") is None


def test_real_cookie_store_errors_are_still_classified() -> None:
    assert classify_cookie_store_error(
        "Extracting cookies from firefox\nERROR: could not find firefox cookies database in 'C:\\x'"
    ) == CHECK_PROFILE_NOT_FOUND
    assert classify_cookie_store_error("ERROR: Failed to load cookies: something broke") == CHECK_FAILED


def test_download_failure_with_browser_cookies_reports_source_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ytdlp = tmp_path / "yt-dlp.exe"
    ytdlp.write_bytes(b"")

    def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=COOKIES_READ_OK + "ERROR: [youtube] abc123: Video unavailable")

    monkeypatch.setattr("pladaz.services.source_adapter.subprocess.run", fake_run)
    adapter = DownloadSourceAdapter(ytdlp_path=ytdlp)
    with pytest.raises(SourceExtractionError) as info:
        adapter.fetch_track_info("https://www.youtube.com/watch?v=abc123", browser_cookies="firefox")
    assert not isinstance(info.value, BrowserCookiesError)


def test_cookie_check_survives_unexpected_error_with_logger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ytdlp = tmp_path / "yt-dlp.exe"
    ytdlp.write_bytes(b"")

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("cannot start process")

    monkeypatch.setattr("pladaz.services.source_adapter.subprocess.run", boom)
    adapter = DownloadSourceAdapter(ytdlp_path=ytdlp, logger=PladazLogger(log_dir=tmp_path / "logs"))
    check = adapter.check_browser_cookies("firefox")
    assert check.state == CHECK_FAILED


def test_unsupported_browser_message_lists_every_supported_browser(tmp_path: Path) -> None:
    bridge, _ = _bridge(tmp_path)
    message = bridge.test_browser_cookies("safari")["error"]["message_en"]
    for label in BROWSER_LABELS.values():
        assert label in message, label


def test_consent_dialog_describes_cookie_access_accurately() -> None:
    dialog = HTML.split('id="modal-browser-consent"', 1)[1].split("<!-- BOARD 20", 1)[0]
    # yt-dlp reads the browser's whole cookie store, not only "session cookies needed by the download tool".
    assert "Reads only session cookies" not in dialog
    assert "all websites" in dialog
    assert "every download" in dialog
    assert "Only continue if you allow this" in dialog


@pytest.mark.real_binaries
def test_real_ytdlp_cookie_check_with_a_throwaway_profile(tmp_path: Path) -> None:
    """Runs the shipped yt-dlp against a fake Firefox profile we create; no real browser data is touched."""
    ytdlp = ROOT / "yt-dlp.exe"
    if not ytdlp.exists():
        pytest.skip("yt-dlp.exe is not present in the project root")
    profile = tmp_path / "profile"
    profile.mkdir()
    con = sqlite3.connect(profile / "cookies.sqlite")
    con.execute(
        "CREATE TABLE moz_cookies (id INTEGER PRIMARY KEY, originAttributes TEXT, name TEXT, value TEXT, host TEXT,"
        " path TEXT, expiry INTEGER, lastAccessed INTEGER, creationTime INTEGER, isSecure INTEGER, isHttpOnly INTEGER,"
        " inBrowserElement INTEGER, sameSite INTEGER, rawSameSite INTEGER, schemeMap INTEGER)"
    )
    con.execute(
        "INSERT INTO moz_cookies (originAttributes,name,value,host,path,expiry,isSecure,isHttpOnly)"
        " VALUES ('','TESTNAME','SECRET_VALUE_MUST_NOT_APPEAR','.example.com','/',4102444800,1,1)"
    )
    con.commit()
    con.close()

    def run(spec: str) -> str:
        proc = subprocess.run(
            [str(ytdlp), "--no-warnings", "--encoding", "utf-8", "-v", "--ignore-config", "--cookies-from-browser", spec],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        return proc.stdout + "\n" + proc.stderr

    ok = run(f"firefox:{profile}")
    assert "SECRET_VALUE_MUST_NOT_APPEAR" not in ok
    readable = parse_cookie_check_output(ok, "firefox")
    assert readable.state == CHECK_READABLE and readable.cookie_count == 1

    missing = parse_cookie_check_output(run(f"firefox:{profile / 'nope'}"), "firefox")
    assert missing.state == CHECK_PROFILE_NOT_FOUND
