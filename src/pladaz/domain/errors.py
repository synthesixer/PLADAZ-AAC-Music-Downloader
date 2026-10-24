"""Error codes and domain exceptions defined in SYSTEM_DESIGN.md Section 4.1."""

from typing import Optional

from pladaz.domain.models import StructuredError


class ErrorCode:
    """Error and warning codes from SYSTEM_DESIGN.md Section 4.1."""

    # Source
    ERR_SOURCE_INVALID_URL = "ERR_SOURCE_INVALID_URL"
    ERR_SOURCE_EXTRACTION_FAILED = "ERR_SOURCE_EXTRACTION_FAILED"
    ERR_SOURCE_NETWORK_TIMEOUT = "ERR_SOURCE_NETWORK_TIMEOUT"
    # Browser-assisted authentication (DEC-052)
    ERR_SOURCE_AUTH_REQUIRED = "ERR_SOURCE_AUTH_REQUIRED"
    ERR_BROWSER_COOKIES_FAILED = "ERR_BROWSER_COOKIES_FAILED"

    # Audio
    ERR_AUDIO_FFMPEG_FAILED = "ERR_AUDIO_FFMPEG_FAILED"

    # Metadata
    ERR_METADATA_TAGGING_FAILED = "ERR_METADATA_TAGGING_FAILED"
    WARN_METADATA_ENRICH_UNAVAILABLE = "WARN_METADATA_ENRICH_UNAVAILABLE"

    # Validator
    ERR_VALIDATOR_CORRUPT_FILE = "ERR_VALIDATOR_CORRUPT_FILE"
    ERR_VALIDATOR_INVALID_CODEC = "ERR_VALIDATOR_INVALID_CODEC"
    ERR_VALIDATOR_MISSING_TITLE = "ERR_VALIDATOR_MISSING_TITLE"
    ERR_VALIDATOR_MISSING_COVER = "ERR_VALIDATOR_MISSING_COVER"

    # SD Card
    ERR_SDCARD_DISCONNECTED = "ERR_SDCARD_DISCONNECTED"
    ERR_SDCARD_INSUFFICIENT_SPACE = "ERR_SDCARD_INSUFFICIENT_SPACE"
    ERR_SDCARD_VERIFY_FAILED = "ERR_SDCARD_VERIFY_FAILED"

    # Path
    ERR_PATH_TOO_LONG = "ERR_PATH_TOO_LONG"

    # Queue
    ERR_TASK_CANCELLED = "ERR_TASK_CANCELLED"
    ERR_TASK_RETRY_FAILED = "ERR_TASK_RETRY_FAILED"
    ERR_TASK_REMOVE_FAILED = "ERR_TASK_REMOVE_FAILED"
    ERR_CONFLICT_NOT_FOUND = "ERR_CONFLICT_NOT_FOUND"

    # System
    ERR_CONFIG_CORRUPT = "ERR_CONFIG_CORRUPT"
    ERR_CONFIG_INVALID = "ERR_CONFIG_INVALID"
    ERR_HISTORY_WRITE_FAILED = "ERR_HISTORY_WRITE_FAILED"
    ERR_YTDLP_UPDATE_FAILED = "ERR_YTDLP_UPDATE_FAILED"


class PladazError(Exception):
    """Base domain exception carrying a StructuredError."""

    def __init__(
        self,
        code: str,
        message_en: str,
        recoverable: bool = False,
        task_id: Optional[str] = None,
        details: Optional[str] = None,
    ) -> None:
        super().__init__(message_en)
        self.structured = StructuredError(
            code=code,
            message_en=message_en,
            recoverable=recoverable,
            task_id=task_id,
            details=details,
        )

    @property
    def code(self) -> str:
        return self.structured.code

    @property
    def message_en(self) -> str:
        return self.structured.message_en

    @property
    def recoverable(self) -> bool:
        return self.structured.recoverable


class PathTooLongError(PladazError):
    """Raised when a full Windows target path exceeds 259 characters (DEC-043)."""

    def __init__(
        self,
        message_en: str = (
            "The target file path exceeds the Windows maximum path length (259 characters). "
            "Try choosing a shorter destination folder."
        ),
        task_id: Optional[str] = None,
        details: Optional[str] = None,
    ) -> None:
        super().__init__(
            code=ErrorCode.ERR_PATH_TOO_LONG,
            message_en=message_en,
            recoverable=False,
            task_id=task_id,
            details=details,
        )


class MetadataTaggingError(PladazError):
    """Raised when reading/processing cover art or writing M4A metadata tags fails."""

    def __init__(
        self,
        message_en: str = "Failed to write metadata tags or cover art to the M4A file.",
        task_id: Optional[str] = None,
        details: Optional[str] = None,
    ) -> None:
        super().__init__(
            code=ErrorCode.ERR_METADATA_TAGGING_FAILED,
            message_en=message_en,
            recoverable=False,
            task_id=task_id,
            details=details,
        )


class SDCardDisconnectedError(PladazError):
    """Raised when the SD card or destination drive is disconnected or inaccessible."""

    def __init__(
        self,
        message_en: str = "The Micro SD Card is disconnected, read-only, or inaccessible.",
        task_id: Optional[str] = None,
        details: Optional[str] = None,
    ) -> None:
        super().__init__(
            code=ErrorCode.ERR_SDCARD_DISCONNECTED,
            message_en=message_en,
            recoverable=True,
            task_id=task_id,
            details=details,
        )


class SDCardInsufficientSpaceError(PladazError):
    """Raised when the SD card does not have enough free space for the file."""

    def __init__(
        self,
        message_en: str = "Insufficient free space on the Micro SD Card.",
        task_id: Optional[str] = None,
        details: Optional[str] = None,
    ) -> None:
        super().__init__(
            code=ErrorCode.ERR_SDCARD_INSUFFICIENT_SPACE,
            message_en=message_en,
            recoverable=True,
            task_id=task_id,
            details=details,
        )


class SDCardVerifyFailedError(PladazError):
    """Raised when the copied file on the SD card fails size or container verification."""

    def __init__(
        self,
        message_en: str = "Failed to verify the copied file on the Micro SD Card.",
        task_id: Optional[str] = None,
        details: Optional[str] = None,
    ) -> None:
        super().__init__(
            code=ErrorCode.ERR_SDCARD_VERIFY_FAILED,
            message_en=message_en,
            recoverable=True,
            task_id=task_id,
            details=details,
        )


class SourceInvalidUrlError(PladazError):
    """Raised when the user submits a URL that is not a valid YouTube or YouTube Music link."""

    def __init__(
        self,
        message_en: str = "Invalid URL. Only YouTube and YouTube Music links are supported.",
        task_id: Optional[str] = None,
        details: Optional[str] = None,
    ) -> None:
        super().__init__(
            code=ErrorCode.ERR_SOURCE_INVALID_URL,
            message_en=message_en,
            recoverable=False,
            task_id=task_id,
            details=details,
        )


class SourceExtractionError(PladazError):
    """Raised when yt-dlp fails to extract metadata/formats or the content is restricted."""

    def __init__(
        self,
        message_en: str = (
            "Failed to extract audio information from YouTube. "
            "Check the URL. If the content needs a signed-in account, set up Browser Authentication in Settings."
        ),
        task_id: Optional[str] = None,
        details: Optional[str] = None,
    ) -> None:
        super().__init__(
            code=ErrorCode.ERR_SOURCE_EXTRACTION_FAILED,
            message_en=message_en,
            recoverable=True,
            task_id=task_id,
            details=details,
        )


class SourceAuthRequiredError(PladazError):
    """Raised when YouTube reports that the content requires a signed-in account (DEC-052)."""

    def __init__(
        self,
        message_en: str = (
            "YouTube requires a signed-in account for this content. "
            "In Settings › Browser Authentication, choose the browser where you are signed in to YouTube."
        ),
        task_id: Optional[str] = None,
        details: Optional[str] = None,
    ) -> None:
        super().__init__(
            code=ErrorCode.ERR_SOURCE_AUTH_REQUIRED,
            message_en=message_en,
            recoverable=True,
            task_id=task_id,
            details=details,
        )


class BrowserCookiesError(PladazError):
    """Raised when yt-dlp cannot read cookies from the browser selected for authentication (DEC-052)."""

    def __init__(
        self,
        message_en: Optional[str] = None,
        task_id: Optional[str] = None,
        details: Optional[str] = None,
        browser: Optional[str] = None,
    ) -> None:
        if message_en is None:
            name = browser.title() if browser else "selected browser"
            message_en = (
                f"PLADAZ could not read cookies from {name}. Open Settings › Browser Authentication "
                "to check it again, choose another browser, or import a cookies.txt file."
            )
        super().__init__(
            code=ErrorCode.ERR_BROWSER_COOKIES_FAILED,
            message_en=message_en,
            recoverable=True,
            task_id=task_id,
            details=details,
        )
        self.browser = browser


class SourceNetworkTimeoutError(PladazError):
    """Raised when a yt-dlp network operation times out."""

    def __init__(
        self,
        message_en: str = "Network timeout while communicating with YouTube.",
        task_id: Optional[str] = None,
        details: Optional[str] = None,
    ) -> None:
        super().__init__(
            code=ErrorCode.ERR_SOURCE_NETWORK_TIMEOUT,
            message_en=message_en,
            recoverable=True,
            task_id=task_id,
            details=details,
        )


class AudioProcessingError(PladazError):
    """Raised when FFmpeg remuxing or encoding to M4A fails."""

    def __init__(
        self,
        message_en: str = "FFmpeg failed to process the audio stream into M4A.",
        task_id: Optional[str] = None,
        details: Optional[str] = None,
    ) -> None:
        super().__init__(
            code=ErrorCode.ERR_AUDIO_FFMPEG_FAILED,
            message_en=message_en,
            recoverable=False,
            task_id=task_id,
            details=details,
        )


class TaskCancelledError(PladazError):
    """Raised when a task is cancelled by the user (DEC-042 -> Failed with ERR_TASK_CANCELLED, recoverable=True)."""

    def __init__(
        self,
        message_en: str = "Task was cancelled by the user.",
        task_id: Optional[str] = None,
        details: Optional[str] = None,
    ) -> None:
        super().__init__(
            code=ErrorCode.ERR_TASK_CANCELLED,
            message_en=message_en,
            recoverable=True,
            task_id=task_id,
            details=details,
        )


