"""Logging service and sensitive data redaction (SYSTEM_DESIGN.md Section 4.2, TC-017, TC-032)."""

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from pladaz.domain.enums import Stage
from pladaz.domain.models import StructuredError

# Proposal values from SYSTEM_DESIGN.md 4.2 (configurable via setup_logger parameters)
DEFAULT_LOG_MAX_BYTES: int = 5 * 1024 * 1024  # 5 MB [Proposal]
DEFAULT_LOG_BACKUP_COUNT: int = 3  # [Proposal]

# Patterns that match Netscape cookies.txt lines, YouTube auth cookies, or bearer tokens
_SENSITIVE_PATTERNS: list[re.Pattern[str]] = [
    # Netscape HTTP Cookie File tab-separated lines (domain, flag, path, secure, expiration, name, value)
    re.compile(
        r"(?m)^[^\r\n\t]+\t(?:TRUE|FALSE)\t[^\r\n\t]+\t(?:TRUE|FALSE)\t\d+\t[^\r\n\t]+\t[^\r\n\t]+$"
    ),
    # Common YouTube / Google session cookie names and values
    re.compile(
        r"(?i)\b(?:SAPISID|APISID|HSID|SSID|SID|LOGIN_INFO|VISITOR_INFO1_LIVE|YSC|PREF|"
        r"__Secure-[13]PSID(?:TS|CC)?|__Secure-[13]PAPISID)\s*[=:\t]\s*[^\s;\"',]+"
    ),
    # Authorization Bearer / OAuth tokens
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*"),
]


def redact_sensitive_text(
    text: Optional[str],
    extra_secrets: Optional[list[str]] = None,
) -> Optional[str]:
    """Remove any cookies.txt content, cookie values, or tokens from a string (TC-032)."""
    if text is None:
        return None

    sanitized = text
    if extra_secrets:
        for secret in extra_secrets:
            if secret and len(secret.strip()) >= 4:
                sanitized = sanitized.replace(secret.strip(), "[REDACTED]")

    for pattern in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub("[REDACTED_COOKIE_OR_TOKEN]", sanitized)

    return sanitized


def build_safe_structured_error(
    code: str,
    message_en: str,
    recoverable: bool,
    task_id: Optional[str] = None,
    details: Optional[str] = None,
    extra_secrets: Optional[list[str]] = None,
) -> StructuredError:
    """Create a StructuredError ensuring details and message contain no sensitive cookie data."""
    safe_message = redact_sensitive_text(message_en, extra_secrets) or message_en
    safe_details = redact_sensitive_text(details, extra_secrets)
    return StructuredError(
        code=code,
        message_en=safe_message,
        recoverable=recoverable,
        task_id=task_id,
        details=safe_details,
    )


class SensitiveDataFilter(logging.Filter):
    """Logging filter that strips cookies.txt content and tokens from every log record."""

    def __init__(self, extra_secrets: Optional[list[str]] = None) -> None:
        super().__init__()
        self._extra_secrets: list[str] = list(extra_secrets) if extra_secrets else []

    def register_secret(self, secret: str) -> None:
        """Register a secret string (e.g. from a loaded cookies.txt) to always redact."""
        cleaned = secret.strip()
        if cleaned and len(cleaned) >= 4 and cleaned not in self._extra_secrets:
            self._extra_secrets.append(cleaned)

    def register_cookies_file_content(self, content: str) -> None:
        """Extract cookie values from a Netscape cookies.txt string and register them for redaction."""
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                cookie_value = parts[6].strip()
                self.register_secret(cookie_value)

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_sensitive_text(record.msg, self._extra_secrets) or ""
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: (
                        redact_sensitive_text(v, self._extra_secrets)
                        if isinstance(v, str)
                        else v
                    )
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    redact_sensitive_text(arg, self._extra_secrets)
                    if isinstance(arg, str)
                    else arg
                    for arg in record.args
                )
        if not hasattr(record, "component"):
            record.component = record.name
        if not hasattr(record, "task_id"):
            record.task_id = "-"
        if not hasattr(record, "stage"):
            record.stage = "-"
        return True


class PladazLogger:
    """Structured application logger wrapping RotatingFileHandler (SYSTEM_DESIGN.md 4.2)."""

    def __init__(
        self,
        log_dir: Path,
        log_filename: str = "pladaz.log",
        max_bytes: int = DEFAULT_LOG_MAX_BYTES,
        backup_count: int = DEFAULT_LOG_BACKUP_COUNT,
        logger_name: str = "pladaz",
    ) -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file_path = self.log_dir / log_filename
        self.max_bytes = max_bytes
        self.backup_count = backup_count

        self._logger = logging.getLogger(f"{logger_name}.{id(self)}")
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False

        self._redaction_filter = SensitiveDataFilter()

        handler = RotatingFileHandler(
            filename=self.log_file_path,
            maxBytes=self.max_bytes,
            backupCount=self.backup_count,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(component)s | task_id=%(task_id)s | stage=%(stage)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        # Ensure millisecond formatting uses comma as shown in SYSTEM_DESIGN.md 4.2
        formatter.default_msec_format = "%s,%03d"
        handler.setFormatter(formatter)
        handler.addFilter(self._redaction_filter)

        self._handler = handler
        self._logger.addHandler(handler)

    @property
    def redaction_filter(self) -> SensitiveDataFilter:
        return self._redaction_filter

    def log(
        self,
        level: int,
        component: str,
        message: str,
        task_id: Optional[str] = None,
        stage: Optional[Stage | str] = None,
    ) -> None:
        stage_str = stage.value if isinstance(stage, Stage) else (stage or "-")
        extra = {
            "component": component,
            "task_id": task_id or "-",
            "stage": stage_str,
        }
        self._logger.log(level, message, extra=extra)
        self._handler.flush()

    def info(
        self,
        component: str,
        message: str,
        task_id: Optional[str] = None,
        stage: Optional[Stage | str] = None,
    ) -> None:
        self.log(logging.INFO, component, message, task_id=task_id, stage=stage)

    def warning(
        self,
        component: str,
        message: str,
        task_id: Optional[str] = None,
        stage: Optional[Stage | str] = None,
    ) -> None:
        self.log(logging.WARNING, component, message, task_id=task_id, stage=stage)

    def error(
        self,
        component: str,
        message: str,
        error_code: Optional[str] = None,
        task_id: Optional[str] = None,
        stage: Optional[Stage | str] = None,
    ) -> None:
        full_msg = f"code={error_code} | {message}" if error_code else message
        self.log(logging.ERROR, component, full_msg, task_id=task_id, stage=stage)

    def close(self) -> None:
        """Close the underlying file handler cleanly (important on Windows before deleting temp dirs)."""
        self._logger.removeHandler(self._handler)
        self._handler.close()

