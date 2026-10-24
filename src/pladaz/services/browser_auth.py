"""Browser detection for browser-assisted authentication (DEC-052).

Detection never opens, copies, or reads any browser file. It only:
1. Reads the Windows registry for browsers registered with Windows (StartMenuInternet / App Paths)
   and the user's default https handler (UserChoice ProgId).
2. Checks whether a browser profile folder that contains a cookie store *exists* (stat only), in the
   per-user data locations that yt-dlp itself reads for `--cookies-from-browser`.

Reading cookies is done only by yt-dlp (`DownloadSourceAdapter.check_browser_cookies`) after the user
explicitly confirms in the UI. Detecting a browser does NOT mean the user is signed in or that cookie
access will succeed.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from typing import Mapping, Optional, Protocol

# Browsers that yt-dlp's `--cookies-from-browser` supports AND that exist on Windows.
# yt-dlp also supports "safari", which is macOS-only, so it is intentionally excluded here.
# Order is used as the fallback recommendation order.
SUPPORTED_BROWSERS: tuple[str, ...] = (
    "firefox",
    "edge",
    "chrome",
    "brave",
    "opera",
    "vivaldi",
    "chromium",
    "whale",
)

BROWSER_LABELS: dict[str, str] = {
    "firefox": "Firefox",
    "edge": "Microsoft Edge",
    "chrome": "Google Chrome",
    "brave": "Brave",
    "opera": "Opera",
    "vivaldi": "Vivaldi",
    "chromium": "Chromium",
    "whale": "Naver Whale",
}

CHROMIUM_FAMILY: frozenset[str] = frozenset(
    {"edge", "chrome", "brave", "opera", "vivaldi", "chromium", "whale"}
)

# Per-user data folders that yt-dlp reads on Windows: (environment variable, relative path).
_PROFILE_ROOTS: dict[str, tuple[str, str]] = {
    "firefox": ("APPDATA", r"Mozilla\Firefox\Profiles"),
    "edge": ("LOCALAPPDATA", r"Microsoft\Edge\User Data"),
    "chrome": ("LOCALAPPDATA", r"Google\Chrome\User Data"),
    "brave": ("LOCALAPPDATA", r"BraveSoftware\Brave-Browser\User Data"),
    "opera": ("APPDATA", r"Opera Software\Opera Stable"),
    "vivaldi": ("LOCALAPPDATA", r"Vivaldi\User Data"),
    "chromium": ("LOCALAPPDATA", r"Chromium\User Data"),
    "whale": ("LOCALAPPDATA", r"Naver\Naver Whale\User Data"),
}

# Lower-case substrings matched against registry StartMenuInternet client names, plus App Paths executables.
_REGISTRY_CLIENT_HINTS: dict[str, tuple[str, ...]] = {
    "firefox": ("firefox",),
    "edge": ("microsoft edge",),
    "chrome": ("google chrome",),
    "brave": ("brave",),
    "opera": ("opera",),
    "vivaldi": ("vivaldi",),
    "chromium": ("chromium",),
    "whale": ("whale",),
}
_APP_PATH_EXES: dict[str, tuple[str, ...]] = {
    "firefox": ("firefox.exe",),
    "edge": ("msedge.exe",),
    "chrome": ("chrome.exe",),
    "brave": ("brave.exe",),
    "opera": ("opera.exe",),
    "vivaldi": ("vivaldi.exe",),
    "chromium": (),
    "whale": ("whale.exe",),
}

# Default https handler ProgId prefixes -> browser key.
_PROGID_PREFIXES: tuple[tuple[str, str], ...] = (
    ("firefoxurl", "firefox"),
    ("msedgehtm", "edge"),
    ("chromehtml", "chrome"),
    ("bravehtml", "brave"),
    ("operastable", "opera"),
    ("vivaldihtm", "vivaldi"),
    ("chromiumhtm", "chromium"),
    ("whalehtml", "whale"),
)

HKEY_CURRENT_USER = "HKCU"
HKEY_LOCAL_MACHINE = "HKLM"

_START_MENU_INTERNET_KEYS: tuple[tuple[str, str], ...] = (
    (HKEY_CURRENT_USER, r"SOFTWARE\Clients\StartMenuInternet"),
    (HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet"),
    (HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Clients\StartMenuInternet"),
)
_APP_PATHS_KEYS: tuple[tuple[str, str], ...] = (
    (HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
    (HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
)
_USER_CHOICE_KEY = (
    HKEY_CURRENT_USER,
    r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice",
)

# Statuses reported per browser by detection (no cookie access is involved).
STATUS_AVAILABLE = "available"  # profile with a cookie store found; cookie access not attempted yet
STATUS_INSTALLED_NO_PROFILE = "installed_no_profile"  # registered with Windows, but no profile/cookie store found
STATUS_NOT_DETECTED = "not_detected"


class RegistryReader(Protocol):
    def list_subkeys(self, hive: str, path: str) -> list[str]: ...

    def read_value(self, hive: str, path: str, name: str) -> Optional[str]: ...


class WindowsRegistryReader:
    """Read-only registry access via `winreg`. Returns empty results on non-Windows or on any error."""

    def _open(self, hive: str, path: str):  # type: ignore[no-untyped-def]
        import winreg  # type: ignore[import-not-found]

        root = winreg.HKEY_CURRENT_USER if hive == HKEY_CURRENT_USER else winreg.HKEY_LOCAL_MACHINE
        return winreg.OpenKey(root, path, 0, winreg.KEY_READ)

    def list_subkeys(self, hive: str, path: str) -> list[str]:
        if os.name != "nt":
            return []
        try:
            import winreg  # type: ignore[import-not-found]

            names: list[str] = []
            with self._open(hive, path) as key:
                idx = 0
                while True:
                    try:
                        names.append(winreg.EnumKey(key, idx))
                    except OSError:
                        break
                    idx += 1
            return names
        except OSError:
            return []

    def read_value(self, hive: str, path: str, name: str) -> Optional[str]:
        if os.name != "nt":
            return None
        try:
            import winreg  # type: ignore[import-not-found]

            with self._open(hive, path) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return str(value) if value is not None else None
        except OSError:
            return None


@dataclass
class BrowserCandidate:
    key: str
    label: str
    status: str
    registered_with_windows: bool
    profile_found: bool
    is_default: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "registered_with_windows": self.registered_with_windows,
            "profile_found": self.profile_found,
            "is_default": self.is_default,
        }


@dataclass
class BrowserDetectionResult:
    browsers: list[BrowserCandidate] = field(default_factory=list)
    recommended: Optional[str] = None
    recommendation_reason: Optional[str] = None
    default_browser: Optional[str] = None

    def to_dict(self) -> dict[str, object]:
        return {
            "browsers": [b.to_dict() for b in self.browsers],
            "recommended": self.recommended,
            "recommendation_reason": self.recommendation_reason,
            "default_browser": self.default_browser,
        }


def browser_label(key: Optional[str]) -> str:
    return BROWSER_LABELS.get(str(key or ""), str(key or "browser"))


def is_supported_browser(key: object) -> bool:
    return isinstance(key, str) and key in SUPPORTED_BROWSERS


def _has_cookie_store(browser: str, root: Path) -> bool:
    """Return True if `root` contains a cookie database file (existence check only; never opened)."""
    try:
        if not root.is_dir():
            return False
        if browser == "firefox":
            return any(p.is_file() for p in root.glob("*/cookies.sqlite"))
        candidates = [
            root / "Network" / "Cookies",
            root / "Cookies",
            root / "Default" / "Network" / "Cookies",
            root / "Default" / "Cookies",
        ]
        if any(p.is_file() for p in candidates):
            return True
        return any(p.is_file() for p in root.glob("Profile */Network/Cookies"))
    except OSError:
        return False


def _registered_browsers(registry: RegistryReader) -> set[str]:
    found: set[str] = set()
    client_names: list[str] = []
    for hive, path in _START_MENU_INTERNET_KEYS:
        client_names.extend(name.lower() for name in registry.list_subkeys(hive, path))
    app_paths: set[str] = set()
    for hive, path in _APP_PATHS_KEYS:
        app_paths.update(name.lower() for name in registry.list_subkeys(hive, path))
    for browser in SUPPORTED_BROWSERS:
        hints = _REGISTRY_CLIENT_HINTS[browser]
        if any(any(h in name for h in hints) for name in client_names):
            found.add(browser)
            continue
        if any(exe in app_paths for exe in _APP_PATH_EXES[browser]):
            found.add(browser)
    return found


def _default_browser(registry: RegistryReader) -> Optional[str]:
    prog_id = registry.read_value(_USER_CHOICE_KEY[0], _USER_CHOICE_KEY[1], "ProgId")
    if not prog_id:
        return None
    lowered = prog_id.lower()
    for prefix, browser in _PROGID_PREFIXES:
        if lowered.startswith(prefix):
            return browser
    return None


def detect_browsers(
    env: Optional[Mapping[str, str]] = None,
    registry: Optional[RegistryReader] = None,
) -> BrowserDetectionResult:
    """Detect supported browsers and recommend one. Never reads cookie contents."""
    environ = env if env is not None else os.environ
    reg = registry if registry is not None else WindowsRegistryReader()

    registered = _registered_browsers(reg)
    default = _default_browser(reg)

    candidates: list[BrowserCandidate] = []
    for browser in SUPPORTED_BROWSERS:
        env_var, rel = _PROFILE_ROOTS[browser]
        base = environ.get(env_var) or ""
        profile_found = bool(base) and _has_cookie_store(browser, Path(base) / rel)
        is_registered = browser in registered
        if profile_found:
            status = STATUS_AVAILABLE
        elif is_registered:
            status = STATUS_INSTALLED_NO_PROFILE
        else:
            status = STATUS_NOT_DETECTED
        candidates.append(
            BrowserCandidate(
                key=browser,
                label=browser_label(browser),
                status=status,
                registered_with_windows=is_registered,
                profile_found=profile_found,
                is_default=(browser == default),
            )
        )

    recommended, reason = recommend_browser(candidates, default)
    return BrowserDetectionResult(
        browsers=candidates,
        recommended=recommended,
        recommendation_reason=reason,
        default_browser=default,
    )


def recommend_browser(
    candidates: list[BrowserCandidate],
    default_browser: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """[Proposal, DEC-052] Prefer Firefox, then the Windows default browser, then the first available one.

    Firefox is preferred because recent Chrome versions on Windows (and possibly other Chromium-based
    browsers) protect their cookies so that other apps such as yt-dlp often cannot read them.
    """
    available = [c.key for c in candidates if c.status == STATUS_AVAILABLE]
    if not available:
        return None, "No supported browser detected on this PC."
    if "firefox" in available:
        return (
            "firefox",
            "Firefox is recommended because Chrome-based browsers on Windows often block other apps from reading their cookies.",
        )
    if default_browser in available:
        return default_browser, f"{browser_label(default_browser)} is your default browser."
    first = available[0]
    return first, f"{browser_label(first)} was found on this PC."


# ---------------------------------------------------------------------------
# Result of an explicit, user-confirmed cookie read attempt (run by yt-dlp)
# ---------------------------------------------------------------------------
CHECK_READABLE = "readable"
CHECK_NO_COOKIES = "no_cookies"
CHECK_PROFILE_NOT_FOUND = "profile_not_found"
CHECK_BROWSER_LOCKED = "browser_locked"
CHECK_ENCRYPTION_BLOCKED = "encryption_blocked"
CHECK_PERMISSION_DENIED = "permission_denied"
CHECK_UNSUPPORTED = "unsupported_browser"
CHECK_YTDLP_MISSING = "ytdlp_missing"
CHECK_TIMEOUT = "timeout"
CHECK_FAILED = "failed"

_EXTRACTED_RE = re.compile(
    r"Extracted (\d+) cookies from (\w+)(?: \((\d+) could not be decrypted\))?",
    re.IGNORECASE,
)

# Substrings in yt-dlp output that mean the *browser cookie store* could not be used.
_PROFILE_MISSING_HINTS = ("could not find", "cookies database")
_LOCKED_HINTS = ("could not copy", "database is locked")
_ENCRYPTION_HINTS = ("dpapi", "app-bound", "could not be decrypted", "cannot decrypt", "failed to decrypt", "no key found")
_PERMISSION_HINTS = ("permission denied", "permissionerror", "access is denied")


@dataclass
class BrowserCookieCheck:
    """Plain-language outcome of a cookie read attempt. Never contains cookie names or values."""

    state: str
    browser: str
    cookie_count: Optional[int]
    message: str
    next_step: str

    @property
    def readable(self) -> bool:
        return self.state == CHECK_READABLE

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "browser": self.browser,
            "browser_label": browser_label(self.browser),
            "cookie_count": self.cookie_count,
            "readable": self.readable,
            "message": self.message,
            "next_step": self.next_step,
        }


def build_cookie_check(state: str, browser: str, cookie_count: Optional[int] = None, undecryptable: int = 0) -> BrowserCookieCheck:
    label = browser_label(browser)
    if state == CHECK_READABLE:
        extra = f" ({undecryptable} could not be decrypted)" if undecryptable else ""
        return BrowserCookieCheck(
            state, browser, cookie_count,
            f"PLADAZ can read cookies from {label}{extra}. This does not confirm that you are signed in to YouTube.",
            f"If a download still asks you to sign in, open {label}, sign in to YouTube, then try again.",
        )
    if state == CHECK_NO_COOKIES:
        return BrowserCookieCheck(
            state, browser, cookie_count,
            f"No cookies were found in {label}.",
            f"Open {label}, sign in to YouTube (or YouTube Music), then press TRY AGAIN.",
        )
    if state == CHECK_PROFILE_NOT_FOUND:
        return BrowserCookieCheck(
            state, browser, None,
            f"PLADAZ could not find a {label} profile on this PC.",
            f"Open {label} at least once and sign in to YouTube, or choose another browser.",
        )
    if state == CHECK_BROWSER_LOCKED:
        return BrowserCookieCheck(
            state, browser, None,
            f"{label} is open and is locking its cookie data.",
            f"Close every {label} window (also check the system tray), then press TRY AGAIN.",
        )
    if state == CHECK_ENCRYPTION_BLOCKED:
        return BrowserCookieCheck(
            state, browser, cookie_count,
            f"{label} protects its cookies so other apps cannot read them. PLADAZ does not try to bypass this protection.",
            "Choose another browser such as Firefox, or import a cookies.txt file instead.",
        )
    if state == CHECK_PERMISSION_DENIED:
        return BrowserCookieCheck(
            state, browser, None,
            f"Windows denied access to {label}'s cookie data. PLADAZ does not try to bypass this restriction.",
            f"Close {label} and try again, or choose another browser.",
        )
    if state == CHECK_UNSUPPORTED:
        return BrowserCookieCheck(
            state, browser, None,
            "This browser is not supported for Browser Authentication.",
            "Choose one of the browsers listed in Settings.",
        )
    if state == CHECK_YTDLP_MISSING:
        return BrowserCookieCheck(
            state, browser, None,
            "yt-dlp.exe is missing, so PLADAZ cannot check browser cookies.",
            "Install or update yt-dlp in Settings first.",
        )
    if state == CHECK_TIMEOUT:
        return BrowserCookieCheck(
            state, browser, None,
            f"Reading cookies from {label} took too long.",
            f"Close {label} and press TRY AGAIN.",
        )
    return BrowserCookieCheck(
        CHECK_FAILED, browser, None,
        f"PLADAZ could not read cookies from {label}.",
        "Try again, choose another browser, or import a cookies.txt file. Technical details were written to the log without cookie values.",
    )


def classify_cookie_store_error(text: str) -> Optional[str]:
    """Return a CHECK_* state if `text` (yt-dlp output) shows the browser cookie store could not be used."""
    lowered = (text or "").lower()
    if "unsupported browser specified for cookies" in lowered:
        return CHECK_UNSUPPORTED
    if "could not find" in lowered and ("cookies database" in lowered or "profile" in lowered):
        return CHECK_PROFILE_NOT_FOUND
    if any(h in lowered for h in _LOCKED_HINTS):
        return CHECK_BROWSER_LOCKED
    if any(h in lowered for h in _ENCRYPTION_HINTS):
        return CHECK_ENCRYPTION_BLOCKED
    if "cookie" in lowered and any(h in lowered for h in _PERMISSION_HINTS):
        return CHECK_PERMISSION_DENIED
    if "failed to load cookies" in lowered or "extracting cookies from" in lowered and "error" in lowered:
        return CHECK_FAILED
    return None


def parse_cookie_check_output(output: str, browser: str) -> BrowserCookieCheck:
    """Interpret yt-dlp output from `--cookies-from-browser <browser>` (no URL, no network)."""
    match = _EXTRACTED_RE.search(output or "")
    if match:
        count = int(match.group(1))
        undecryptable = int(match.group(3) or 0)
        if count > 0:
            return build_cookie_check(CHECK_READABLE, browser, count, undecryptable)
        if undecryptable > 0:
            return build_cookie_check(CHECK_ENCRYPTION_BLOCKED, browser, 0)
        return build_cookie_check(CHECK_NO_COOKIES, browser, 0)
    state = classify_cookie_store_error(output) or CHECK_FAILED
    return build_cookie_check(state, browser)
