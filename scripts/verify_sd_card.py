#!/usr/bin/env python3
"""Read-only verification script for Micro SD Card content (Phase 5, Section 5.1 E).

Validates folder structure, filenames, audio codec (AAC-LC), MP4 atoms,
album art (800x800 JPEG), absence of orphaned .pladaz-tmp files, and
optionally cross-checks against history.json.
"""

import argparse
from io import BytesIO
import json
from pathlib import Path
import re
import sys
from typing import Any, Optional

try:
    from mutagen.mp4 import MP4, MP4Cover
    from PIL import Image
except ImportError:
    print("ERROR: mutagen and pillow are required. Run inside project venv:")
    print("  .\\venv\\Scripts\\python.exe scripts\\verify_sd_card.py <SD_PATH>")
    sys.exit(1)

FORBIDDEN_CHARS_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
MAX_COMPONENT_LENGTH = 100


def verify_file(
    file_path: Path,
    sd_root: Path,
    require_cover: bool = False,
) -> tuple[bool, list[str], dict[str, Any]]:
    """Inspect a single .m4a file on the SD Card. Returns (is_ok, issues, report_dict)."""
    issues: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {
        "rel_path": str(file_path.relative_to(sd_root)),
        "size_bytes": file_path.stat().st_size,
    }

    # 1. Check relative hierarchy: <Album Artist>/<Album>/<Title>.m4a
    rel = file_path.relative_to(sd_root)
    parts = rel.parts
    if len(parts) != 3:
        warnings.append(
            f"Expected depth 3 (<Artist>/<Album>/<Title>.m4a), found {len(parts)} parts: {rel}"
        )

    # 2. Check forbidden characters and component length
    for comp in parts:
        stem = Path(comp).stem if comp == parts[-1] else comp
        if FORBIDDEN_CHARS_RE.search(stem):
            issues.append(f"Component '{comp}' contains forbidden Windows characters.")
        if len(stem) > MAX_COMPONENT_LENGTH:
            issues.append(
                f"Component '{stem[:30]}...' length ({len(stem)}) exceeds max {MAX_COMPONENT_LENGTH} chars."
            )

    # 3. Read MP4 tags and atoms with mutagen
    try:
        mp4 = MP4(file_path)
    except Exception as exc:
        issues.append(f"Cannot parse M4A container: {exc}")
        return False, issues, details

    # 4. Check audio codec
    codec = getattr(mp4.info, "codec", None)
    codec_desc = getattr(mp4.info, "codec_description", "")
    details["codec"] = codec or codec_desc
    if codec and "aac" not in str(codec).lower() and "mp4a" not in str(codec).lower():
        issues.append(f"Audio stream codec is '{codec}', expected AAC-LC.")

    # 5. Check metadata fields
    title = mp4.tags.get("\xa9nam")
    details["title"] = title[0] if title else None
    if not title or not str(title[0]).strip():
        issues.append("Missing mandatory Title atom (\\xa9nam).")

    track_artist = mp4.tags.get("\xa9ART")
    details["track_artist"] = track_artist[0] if track_artist else None

    album_artist = mp4.tags.get("aART")
    details["album_artist"] = album_artist[0] if album_artist else None

    album = mp4.tags.get("\xa9alb")
    details["album"] = album[0] if album else None

    trkn = mp4.tags.get("trkn")
    details["trkn"] = trkn[0] if trkn else None

    disk = mp4.tags.get("disk")
    details["disk"] = disk[0] if disk else None

    year = mp4.tags.get("\xa9day")
    details["year"] = year[0] if year else None

    genre = mp4.tags.get("\xa9gen")
    details["genre"] = genre[0] if genre else None

    # 6. Check cover art (covr atom)
    covers = mp4.tags.get("covr")
    if not covers:
        if require_cover:
            issues.append("Missing album art cover in covr atom (strict mode enabled).")
        else:
            warnings.append("No cover art embedded in covr atom.")
        details["cover"] = None
    else:
        cover_data = covers[0]
        details["cover_format"] = (
            "JPEG" if cover_data.imageformat == MP4Cover.FORMAT_JPEG else "PNG/OTHER"
        )
        try:
            with Image.open(BytesIO(cover_data)) as im:
                details["cover_size"] = im.size
                details["cover_mode"] = im.mode
                if im.size != (800, 800):
                    warnings.append(
                        f"Cover art dimensions {im.size} differ from 800x800 standard."
                    )
                if im.format != "JPEG":
                    warnings.append(f"Cover art format is {im.format}, expected JPEG.")
        except Exception as exc:
            issues.append(f"Corrupt image bytes in covr atom: {exc}")

    all_issues = issues + warnings
    is_ok = len(issues) == 0
    return is_ok, all_issues, details


def verify_sd_card(
    sd_path: Path,
    history_path: Optional[Path] = None,
    require_cover: bool = False,
) -> int:
    """Run full read-only scan of SD Card and print verification report."""
    if not sd_path.exists():
        print(f"ERROR: Destination path does not exist: '{sd_path}'")
        return 1

    print("=" * 65)
    print(f"  PLADAZ Micro SD Card Verification Tool (Read-Only)  ")
    print("=" * 65)
    print(f"Scanning target: {sd_path.resolve()}")

    # Check for orphaned .pladaz-tmp files
    tmp_files = list(sd_path.rglob("*.pladaz-tmp"))
    if tmp_files:
        print(f"\n[WARNING] Found {len(tmp_files)} orphaned temporary (.pladaz-tmp) file(s):")
        for tf in tmp_files:
            print(f"  - {tf.relative_to(sd_path)} ({tf.stat().st_size} bytes)")
    else:
        print("  -> Orphaned .pladaz-tmp files: 0 (Clean)")

    # Find all .m4a files
    m4a_files = sorted(sd_path.rglob("*.m4a"))
    print(f"  -> Total .m4a tracks found: {len(m4a_files)}\n")

    if not m4a_files:
        print("No .m4a files found in destination folder.")
        return 0

    passed_count = 0
    failed_count = 0
    files_summary: list[dict[str, Any]] = []

    for file_path in m4a_files:
        is_ok, issues, details = verify_file(
            file_path=file_path,
            sd_root=sd_path,
            require_cover=require_cover,
        )
        status_tag = "PASS" if is_ok else "FAIL"
        if is_ok:
            passed_count += 1
        else:
            failed_count += 1

        print(f"[{status_tag}] {details['rel_path']}")
        print(
            f"       Title: {details.get('title') or '(None)'} | "
            f"Artist: {details.get('track_artist') or details.get('album_artist') or '(None)'} | "
            f"Cover: {details.get('cover_size', 'None')}"
        )
        if issues:
            for issue in issues:
                prefix = "  WARNING" if "WARNING" in issue or "differ" in issue or "depth" in issue else "  ERROR"
                print(f"       {prefix}: {issue}")

        files_summary.append(details)

    # Cross-reference with history.json if available
    if history_path and history_path.exists():
        print("\n" + "-" * 65)
        print(f"Cross-referencing with history: {history_path.name}")
        try:
            history_data = json.loads(history_path.read_text(encoding="utf-8"))
            # history.json is {"schema_version": 1, "entries": [...]}
            completed_entries = [
                e
                for e in history_data.get("entries", [])
                if isinstance(e, dict) and e.get("status") == "Completed"
            ]
            print(f"  -> Completed entries in history: {len(completed_entries)}")
            print(f"  -> Files present on SD card: {len(m4a_files)}")
        except Exception as exc:
            print(f"  -> Could not parse history.json: {exc}")

    print("\n" + "=" * 65)
    print(f"  VERIFICATION SUMMARY: {passed_count} Passed, {failed_count} Failed")
    if tmp_files:
        print(f"  ORPHANED TEMP FILES: {len(tmp_files)} found (Investigate)")
    print("=" * 65)

    return 0 if failed_count == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify PLADAZ output files and structure on Micro SD Card."
    )
    parser.add_argument(
        "sd_path",
        type=Path,
        help="Path to Micro SD Card drive root or music folder.",
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=None,
        help="Optional path to history.json to cross-reference.",
    )
    parser.add_argument(
        "--require-cover",
        action="store_true",
        help="Fail verification if album cover is missing (strict mode).",
    )
    args = parser.parse_args()
    return verify_sd_card(
        sd_path=args.sd_path,
        history_path=args.history,
        require_cover=args.require_cover,
    )


if __name__ == "__main__":
    sys.exit(main())

