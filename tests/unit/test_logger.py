"""Unit tests for PladazLogger and sensitive data redaction (TC-017, TC-032)."""

from pathlib import Path

from pladaz.domain.enums import Stage
from pladaz.domain.errors import ErrorCode
from pladaz.services.logger import (
    PladazLogger,
    build_safe_structured_error,
    redact_sensitive_text,
)


def test_tc017_error_logging_contains_required_diagnostic_fields(tmp_path: Path) -> None:
    """TC-017: Simulated errors record timestamp, level, component, task_id, stage, and error code."""
    log_dir = tmp_path / "logs"
    logger = PladazLogger(
        log_dir=log_dir,
        max_bytes=1024 * 1024,
        backup_count=2,
    )
    try:
        logger.info(
            component="QueueWorker",
            message="Starting FFmpeg remux",
            task_id="task-b4a1",
            stage=Stage.PROCESSING_AUDIO,
        )
        logger.error(
            component="AudioProcessingService",
            message="FFmpeg exited with code 1",
            error_code=ErrorCode.ERR_AUDIO_FFMPEG_FAILED,
            task_id="task-b4a1",
            stage=Stage.PROCESSING_AUDIO,
        )
    finally:
        logger.close()

    log_file = log_dir / "pladaz.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")

    assert "INFO | QueueWorker | task_id=task-b4a1 | stage=processing_audio | Starting FFmpeg remux" in content
    assert (
        f"ERROR | AudioProcessingService | task_id=task-b4a1 | stage=processing_audio | "
        f"code={ErrorCode.ERR_AUDIO_FFMPEG_FAILED} | FFmpeg exited with code 1"
    ) in content


def test_tc032_cookies_and_tokens_never_appear_in_logs_or_structured_error(
    tmp_path: Path,
) -> None:
    """TC-032: Ensure cookies.txt content, session cookies, and tokens are redacted from logs and StructuredError.details."""
    sample_cookies_txt = (
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t1760000000\tSAPISID\tsecret_sapisid_value_998877\n"
        ".youtube.com\tTRUE\t/\tTRUE\t1760000000\t__Secure-3PSID\tsuper_secret_3psid_token_xyz\n"
        ".youtube.com\tTRUE\t/\tFALSE\t1760000000\tCUSTOM_COOKIE\tmy_custom_secret_cookie_val\n"
    )

    log_dir = tmp_path / "logs"
    logger = PladazLogger(log_dir=log_dir)
    try:
        logger.redaction_filter.register_cookies_file_content(sample_cookies_txt)

        # Log messages containing raw cookies.txt lines, cookie key=value, and Bearer tokens
        logger.error(
            component="DownloadSourceAdapter",
            message=(
                f"Extraction failed with cookies:\n{sample_cookies_txt}\n"
                "Header Cookie: SAPISID=secret_sapisid_value_998877; "
                "__Secure-1PSID=inline_secret_1psid_val "
                "Authorization: Bearer ya29.a0AfH6SMBxSecretToken12345 "
                "Custom leaked value: my_custom_secret_cookie_val"
            ),
            error_code=ErrorCode.ERR_SOURCE_EXTRACTION_FAILED,
            task_id="task-cookie-test",
            stage=Stage.FETCHING_INFO,
        )
    finally:
        logger.close()

    log_content = (log_dir / "pladaz.log").read_text(encoding="utf-8")
    assert "secret_sapisid_value_998877" not in log_content
    assert "super_secret_3psid_token_xyz" not in log_content
    assert "my_custom_secret_cookie_val" not in log_content
    assert "inline_secret_1psid_val" not in log_content
    assert "ya29.a0AfH6SMBxSecretToken12345" not in log_content
    assert "[REDACTED" in log_content

    # Also verify StructuredError.details redaction
    err = build_safe_structured_error(
        code=ErrorCode.ERR_SOURCE_EXTRACTION_FAILED,
        message_en="Failed to extract track info.",
        recoverable=True,
        task_id="task-cookie-test",
        details=(
            f"yt-dlp stderr dumped cookie line:\n{sample_cookies_txt}\n"
            "SAPISID=secret_sapisid_value_998877"
        ),
        extra_secrets=["my_custom_secret_cookie_val"],
    )
    assert err.details is not None
    assert "secret_sapisid_value_998877" not in err.details
    assert "super_secret_3psid_token_xyz" not in err.details
    assert "my_custom_secret_cookie_val" not in err.details


def test_logger_configurable_rotation(tmp_path: Path) -> None:
    """Verify max_bytes and backup_count parameters rotate log files as configured."""
    log_dir = tmp_path / "logs"
    logger = PladazLogger(
        log_dir=log_dir,
        max_bytes=250,
        backup_count=2,
    )
    try:
        for i in range(10):
            logger.info("RotationTest", f"Log message number {i} with padding text")
    finally:
        logger.close()

    assert (log_dir / "pladaz.log").exists()
    assert (log_dir / "pladaz.log.1").exists()
    assert (log_dir / "pladaz.log.2").exists()
    assert not (log_dir / "pladaz.log.3").exists()

