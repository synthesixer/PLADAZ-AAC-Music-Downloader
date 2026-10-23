"""Domain enumerations defined according to SYSTEM_DESIGN.md 2.1 and IMPLEMENT_PLAN.md."""

from enum import Enum


class TaskStatus(str, Enum):
    """IR-017: Strictly 4 primary task statuses."""

    QUEUED = "Queued"
    DOWNLOADING = "Downloading"
    COMPLETED = "Completed"
    FAILED = "Failed"


class ConflictAction(str, Enum):
    """DEC-019: User action when a destination file conflict occurs."""

    OVERWRITE = "overwrite"
    SKIP = "skip"
    KEEP_BOTH = "keep_both"


class ConflictScope(str, Enum):
    """DEC-019, DEC-044: Scope for applying conflict resolution."""

    SINGLE = "single"
    ALBUM = "album"
    QUEUE = "queue"


class AudioProcessMode(str, Enum):
    """DEC-033: Audio stream processing mode."""

    REMUX_AAC = "remux_aac"
    ENCODE_AAC_LC = "encode_aac_lc"


class Stage(str, Enum):
    """Sub-stages within TaskStatus.DOWNLOADING (not a primary status)."""

    CHECKING_SD = "checking_sd"
    FETCHING_INFO = "fetching_info"
    RESOLVING_METADATA = "resolving_metadata"
    CHECKING_DUPLICATE = "checking_duplicate"
    WAITING_CONFLICT = "waiting_conflict"
    DOWNLOADING_STREAM = "downloading_stream"
    PROCESSING_AUDIO = "processing_audio"
    TAGGING = "tagging"
    VALIDATING = "validating"
    COPYING = "copying"

