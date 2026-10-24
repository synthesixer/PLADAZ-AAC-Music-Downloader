"""Regression tests for backend changes behind the 2026-10-24 UX/UI fixes (UX-11 multi-link add)."""

from pathlib import Path
import pytest

pytestmark = pytest.mark.integration

from pladaz.domain.errors import ErrorCode
from tests.integration.test_audit_fixes import BlockingAdapter, _bridge


def test_ux11_enqueue_urls_keeps_going_after_a_bad_line(tmp_path: Path) -> None:
    """One bad line must not hide the tracks already added from the other lines."""
    bridge, _ = _bridge(tmp_path)

    res = bridge.enqueue_urls(
        "https://www.youtube.com/playlist?list=PL1\nhttps://example.com/not-youtube\n"
    )

    assert res["success"] is False
    assert len(res["tasks_added"]) == len(BlockingAdapter().extract_entries("x"))
    assert [e["url"] for e in res["failed_lines"]] == ["https://example.com/not-youtube"]
    assert res["failed_lines"][0]["error"]["code"] == ErrorCode.ERR_SOURCE_INVALID_URL
    assert res["error"]["code"] == ErrorCode.ERR_SOURCE_INVALID_URL


def test_ux11_enqueue_urls_all_good(tmp_path: Path) -> None:
    bridge, _ = _bridge(tmp_path)
    res = bridge.enqueue_urls("https://www.youtube.com/playlist?list=PL1")
    assert res["success"] is True
    assert res["failed_lines"] == []
    assert res["error"] is None
