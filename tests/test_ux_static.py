"""Static checks for the 2026-10-24 UX/UI audit fixes (markup, tokens, copy) that the Node harness cannot see."""

from pathlib import Path
import re
import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "ui" / "js" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "ui_src" / "input.css").read_text(encoding="utf-8")


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _token(name: str) -> str:
    return re.search(rf"--{name}:\s*(#[0-9A-Fa-f]{{6}})", CSS).group(1)


def test_ux01_action_pink_passes_contrast_with_white() -> None:
    assert _token("accent").upper() == "#CC2982"
    assert _contrast("#FFFFFF", _token("accent")) >= 4.5
    assert re.search(r"\.btn-p\s*{[^}]*background:\s*var\(--accent\)", CSS)
    assert re.search(r"\.pbtn\.hot\s*{[^}]*background:\s*var\(--accent\)", CSS)
    for src in (HTML, APP_JS):
        assert "bg-[var(--hot)] text-white" not in src, "white text must not sit on the light --hot pink"


def test_ux13_header_subtitle_is_white() -> None:
    assert "text-[#E9E2FF]" not in HTML


def test_ux02_live_region_and_progressbar_exist() -> None:
    assert re.search(r'id="sr-status"[^>]*aria-live="polite"', HTML)
    assert re.search(r'id="deck-progress-segments"[^>]*role="progressbar"', HTML)
    assert 'role="progressbar"' in APP_JS


def test_ux03_icon_buttons_in_markup_have_names() -> None:
    for btn in re.findall(r"<button[^>]*class=\"[^\"]*\bibtn\b[^\"]*\"[^>]*>", HTML):
        assert "aria-label=" in btn, btn


def test_ux05_conflict_keep_both_is_primary_and_overwrite_is_danger() -> None:
    assert re.search(r'id="conflict-keep-both-btn"[^>]*class="btn btn-p"', HTML)
    assert re.search(r'id="conflict-overwrite-btn"[^>]*class="btn btn-d"', HTML)
    assert "same destination folder" in HTML
    assert "until the queue is empty" in HTML


def test_ux06_settings_have_no_save_button() -> None:
    assert 'id="settings-save-btn"' not in HTML
    assert 'id="settings-discard-btn"' not in HTML


def test_ux07_bezels_and_system_dialogs_follow_design() -> None:
    for section in ("view-queue", "view-track", "view-storage", "view-settings", "view-history"):
        block = HTML.split(f'id="{section}"', 1)[1][:600]
        assert "bg-[var(--pinkbz)]" not in block, f"{section} bezel must be lavender"
    deck = HTML.split('id="now-processing-bezel"', 1)[1][:300]
    assert "bg-[var(--pinkbz)]" in deck, "Now Processing is the live (pink) bezel"
    for dialog in ("modal-disclaimer", "modal-conflict", "modal-cancel-confirm", "modal-clear-history",
                   "modal-error-log", "modal-browser-consent"):
        block = HTML.split(f'id="{dialog}"', 1)[1][:400]
        assert "pxwin" in block, f"{dialog} must use the pixel-window style"
    assert ".pxwin" in CSS


def test_ux08_settings_controls_have_programmatic_labels() -> None:
    assert re.search(r'<label[^>]*for="settings-mb-ua-input"', HTML)
    assert re.search(r'id="settings-require-cover-checkbox"[^>]*aria-labelledby="settings-require-cover-title"', HTML)


def test_ux11_link_box_is_multiline() -> None:
    assert re.search(r'<textarea[^>]*id="url-input"', HTML)


def test_ux10_ux14_copy_is_current() -> None:
    for stale in ("Select tracks", "alongside PLADAZ.exe", "STANDALONE", "BROWSE…", "☰ HIST<", "⚙ SET<", "▣ CARD<"):
        assert stale not in HTML, stale
