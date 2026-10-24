"""Unit tests for Browser Authentication detection, recommendation, and plain-language checks."""

from pathlib import Path
import pytest

pytestmark = pytest.mark.unit

from pladaz.domain.errors import (
    ErrorCode,
    BrowserCookiesError,
    SourceAuthRequiredError,
)
from pladaz.services.browser_auth import (
    CHECK_BROWSER_LOCKED,
    CHECK_ENCRYPTION_BLOCKED,
    CHECK_NO_COOKIES,
    CHECK_PERMISSION_DENIED,
    CHECK_PROFILE_NOT_FOUND,
    CHECK_READABLE,
    CHECK_TIMEOUT,
    CHECK_UNSUPPORTED,
    STATUS_AVAILABLE,
    STATUS_INSTALLED_NO_PROFILE,
    STATUS_NOT_DETECTED,
    BrowserCandidate,
    BrowserDetectionResult,
    RegistryReader,
    browser_label,
    classify_cookie_store_error,
    detect_browsers,
    is_supported_browser,
    parse_cookie_check_output,
    recommend_browser,
)


class FakeRegistry(RegistryReader):
    def __init__(
        self,
        subkeys: dict[tuple[str, str], list[str]] = None,
        values: dict[tuple[str, str, str], str] = None,
    ):
        self.subkeys = subkeys or {}
        self.values = values or {}

    def list_subkeys(self, hive: str, path: str) -> list[str]:
        return self.subkeys.get((hive, path), [])

    def read_value(self, hive: str, path: str, name: str) -> str | None:
        return self.values.get((hive, path, name))


def test_supported_browser_keys_and_labels() -> None:
    assert is_supported_browser("chrome") is True
    assert is_supported_browser("firefox") is True
    assert is_supported_browser("edge") is True
    assert is_supported_browser("brave") is True
    assert is_supported_browser("safari") is False
    assert is_supported_browser(123) is False
    assert is_supported_browser("") is False

    assert browser_label("firefox") == "Firefox"
    assert browser_label("chrome") == "Google Chrome"
    assert browser_label("edge") == "Microsoft Edge"
    assert browser_label("brave") == "Brave"
    assert browser_label("unknown") == "unknown"


def test_recommendation_prefers_firefox_due_to_windows_encryption() -> None:
    # When both Firefox and Chrome (or Edge) are detected, Firefox must be recommended
    candidates = [
        BrowserCandidate(key="chrome", label="Google Chrome", status=STATUS_AVAILABLE, registered_with_windows=True, profile_found=True, is_default=True),
        BrowserCandidate(key="firefox", label="Firefox", status=STATUS_AVAILABLE, registered_with_windows=True, profile_found=True, is_default=False),
        BrowserCandidate(key="edge", label="Microsoft Edge", status=STATUS_AVAILABLE, registered_with_windows=True, profile_found=True, is_default=False),
    ]
    rec, reason = recommend_browser(candidates, default_browser="chrome")
    assert rec == "firefox"
    assert "Firefox" in reason
    assert "block" in reason.lower() or "protect" in reason.lower()


def test_recommendation_falls_back_to_default_browser_when_firefox_absent() -> None:
    candidates = [
        BrowserCandidate(key="edge", label="Microsoft Edge", status=STATUS_AVAILABLE, registered_with_windows=True, profile_found=True, is_default=True),
        BrowserCandidate(key="chrome", label="Google Chrome", status=STATUS_AVAILABLE, registered_with_windows=True, profile_found=True, is_default=False),
    ]
    rec, reason = recommend_browser(candidates, default_browser="edge")
    assert rec == "edge"
    assert "default browser" in reason.lower()


def test_recommendation_falls_back_to_first_candidate_when_no_default_match() -> None:
    candidates = [
        BrowserCandidate(key="brave", label="Brave", status=STATUS_AVAILABLE, registered_with_windows=True, profile_found=True, is_default=False),
        BrowserCandidate(key="opera", label="Opera", status=STATUS_AVAILABLE, registered_with_windows=True, profile_found=True, is_default=False),
    ]
    rec, reason = recommend_browser(candidates, default_browser="safari")
    assert rec == "brave"
    assert "Brave was found on this PC" in reason


def test_recommendation_when_no_browsers_detected() -> None:
    rec, reason = recommend_browser([], default_browser=None)
    assert rec is None
    assert "No supported browser detected" in reason


def test_detect_browsers_with_fake_registry_and_tmp_profiles(tmp_path: Path) -> None:
    # Setup simulated profile dirs
    # Firefox is in APPDATA / Mozilla\Firefox\Profiles
    ff_root = tmp_path / "appdata" / "Mozilla" / "Firefox" / "Profiles"
    ff_profile = ff_root / "test.default"
    ff_profile.mkdir(parents=True)
    (ff_profile / "cookies.sqlite").write_bytes(b"sqlite-mock")

    # Edge is in LOCALAPPDATA / Microsoft\Edge\User Data
    edge_root = tmp_path / "localappdata" / "Microsoft" / "Edge" / "User Data"
    edge_default = edge_root / "Default"
    edge_default.mkdir(parents=True)
    (edge_default / "Cookies").write_bytes(b"cookies-mock")

    env = {
        "APPDATA": str(tmp_path / "appdata"),
        "LOCALAPPDATA": str(tmp_path / "localappdata"),
    }

    # Setup simulated registry
    fake_reg = FakeRegistry(
        subkeys={
            ("HKLM", r"SOFTWARE\Clients\StartMenuInternet"): ["FIREFOX.EXE", "Microsoft Edge"],
        },
        values={
            ("HKCU", r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice", "ProgId"): "MSEdgeHTM",
        },
    )

    result = detect_browsers(env=env, registry=fake_reg)
    assert isinstance(result, BrowserDetectionResult)
    detected_keys = [b.key for b in result.browsers if b.status == STATUS_AVAILABLE]
    assert "firefox" in detected_keys
    assert "edge" in detected_keys
    assert result.default_browser == "edge"
    assert result.recommended == "firefox"


def test_parse_cookie_check_output_readable() -> None:
    output = "[Cookies] Extracting cookies from firefox\n[Cookies] Extracted 42 cookies from firefox\n"
    check = parse_cookie_check_output(output, "firefox")
    assert check.readable is True
    assert check.state == CHECK_READABLE
    assert check.cookie_count == 42
    assert "Firefox" in check.message
    assert "PLADAZ can read cookies from Firefox" in check.message


def test_parse_cookie_check_output_encryption_blocked() -> None:
    output = (
        "[Cookies] Extracting cookies from chrome\n"
        "[Cookies] Extracted 0 cookies from chrome (15 could not be decrypted)\n"
    )
    check = parse_cookie_check_output(output, "chrome")
    assert check.readable is False
    assert check.state == CHECK_ENCRYPTION_BLOCKED
    assert "protects its cookies" in check.message
    assert "Firefox" in check.next_step


def test_parse_cookie_check_output_database_locked() -> None:
    output = "ERROR: Failed to load cookies: sqlite3.OperationalError: database is locked\n"
    check = parse_cookie_check_output(output, "edge")
    assert check.readable is False
    assert check.state == CHECK_BROWSER_LOCKED
    assert "locking its cookie data" in check.message
    assert "Close every Microsoft Edge window" in check.next_step


def test_parse_cookie_check_output_profile_not_found() -> None:
    output = "ERROR: Could not find any Brave profile to extract cookies from\n"
    check = parse_cookie_check_output(output, "brave")
    assert check.readable is False
    assert check.state == CHECK_PROFILE_NOT_FOUND
    assert "could not find a Brave profile" in check.message


def test_parse_cookie_check_output_permission_denied() -> None:
    output = "ERROR: Permission denied when reading cookie file from /path\n"
    check = parse_cookie_check_output(output, "opera")
    assert check.readable is False
    assert check.state == CHECK_PERMISSION_DENIED
    assert "denied access" in check.message


def test_parse_cookie_check_output_unsupported() -> None:
    output = "ERROR: Unsupported browser specified for cookies: safari\n"
    check = parse_cookie_check_output(output, "safari")
    assert check.readable is False
    assert check.state == CHECK_UNSUPPORTED
    assert "not supported" in check.message


def test_error_classes_and_codes() -> None:
    auth_err = SourceAuthRequiredError(
        message_en="This video is age-restricted.",
        details="Sign in to confirm your age",
    )
    assert auth_err.code == ErrorCode.ERR_SOURCE_AUTH_REQUIRED
    assert auth_err.recoverable is True
    assert "age-restricted" in auth_err.message_en

    b_err = BrowserCookiesError(
        browser="chrome",
        message_en="Could not read cookies from Chrome.",
        details="database is locked",
    )
    assert b_err.code == ErrorCode.ERR_BROWSER_COOKIES_FAILED
    assert b_err.recoverable is True
    assert "Chrome" in b_err.message_en
    assert b_err.browser == "chrome"

