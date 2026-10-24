"""Measure the TBA-023 performance criteria fixed in DEC-054 (no network, no real music).

Criteria (owner decision 2026-10-24):
  1. App start: `PLADAZ.exe --smoke-test` finishes within 5 s (backend start-up + initial state).
     The WebView2 window paint is not included; check it by eye on the target PC.
  2. Post-download stages for a 5-minute track (FFmpeg remux or encode + tagging + Output Validator +
     Copy & Verify) finish within 30 s. Download time is excluded because it depends on the network.

Usage:
  .\\venv\\Scripts\\python.exe scripts\\measure_performance.py [--exe dist\\PLADAZ\\PLADAZ.exe]
      [--ffmpeg dist\\PLADAZ\\_internal\\bin\\ffmpeg.exe] [--dest E:\\PLADAZ-perf-test]

`--dest` defaults to a temporary folder on the PC; point it at a folder on the Micro SD card to include
the card's write speed. The script only writes inside that folder and deletes its own test file.
"""

import argparse
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402

from pladaz.domain.enums import AudioProcessMode  # noqa: E402
from pladaz.domain.models import TrackMetadata  # noqa: E402
from pladaz.services.audio_processor import AudioProcessingService  # noqa: E402
from pladaz.services.metadata_service import MetadataAlbumArtService  # noqa: E402
from pladaz.services.output_validator import OutputValidator  # noqa: E402
from pladaz.services.sd_card_manager import SDCardManager  # noqa: E402

START_LIMIT_SEC = 5.0
POST_DOWNLOAD_LIMIT_SEC = 30.0
TRACK_SECONDS = 300


def _make_source(ffmpeg: Path, out: Path, codec_args: list[str]) -> None:
    subprocess.run(
        [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", f"sine=frequency=440:duration={TRACK_SECONDS}:sample_rate=44100", "-ac", "2", *codec_args, str(out)],
        check=True, capture_output=True,
    )


def _cover_jpeg() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (1280, 720), (122, 95, 224)).save(buf, format="JPEG")
    return MetadataAlbumArtService().process_cover(buf.getvalue())


def measure_post_download(ffmpeg: Path, mode: AudioProcessMode, source: Path, dest_root: Path, work: Path) -> dict:
    processor = AudioProcessingService(ffmpeg_path=ffmpeg)
    tagger = MetadataAlbumArtService()
    validator = OutputValidator()
    sd = SDCardManager()
    meta = TrackMetadata(title="PLADAZ Performance Test", track_artist="PLADAZ", album="Perf", album_artist="PLADAZ",
                         track_number=1, total_tracks=None, disc_number=1, total_discs=None, year="2026",
                         genre="Test", cover_jpeg=_cover_jpeg())
    out = work / f"processed-{mode.value}.m4a"
    target = dest_root / "PLADAZ" / "Perf" / f"PLADAZ Performance Test ({mode.value}).m4a"
    t0 = time.perf_counter()
    processor.to_m4a(source, out, mode)
    t1 = time.perf_counter()
    tagger.write_m4a_tags(out, meta)
    t2 = time.perf_counter()
    result = validator.validate(out, require_cover=True)
    t3 = time.perf_counter()
    sd.copy_and_verify(out, target, overwrite=True)
    t4 = time.perf_counter()
    target.unlink(missing_ok=True)
    total = t4 - t0
    return {
        "mode": mode.value,
        "valid": result.is_valid,
        "ffmpeg_sec": round(t1 - t0, 2),
        "tagging_sec": round(t2 - t1, 2),
        "validate_sec": round(t3 - t2, 2),
        "copy_verify_sec": round(t4 - t3, 2),
        "total_sec": round(total, 2),
        "limit_sec": POST_DOWNLOAD_LIMIT_SEC,
        "pass": bool(result.is_valid and total <= POST_DOWNLOAD_LIMIT_SEC),
    }


def measure_start(exe: Path) -> dict:
    t0 = time.perf_counter()
    proc = subprocess.run([str(exe), "--smoke-test"], capture_output=True, timeout=60)
    elapsed = time.perf_counter() - t0
    return {"exit_code": proc.returncode, "seconds": round(elapsed, 2), "limit_sec": START_LIMIT_SEC,
            "pass": proc.returncode == 0 and elapsed <= START_LIMIT_SEC}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exe", type=Path, default=ROOT / "dist" / "PLADAZ" / "PLADAZ.exe")
    parser.add_argument("--ffmpeg", type=Path, default=ROOT / "dist" / "PLADAZ" / "_internal" / "bin" / "ffmpeg.exe")
    parser.add_argument("--dest", type=Path, default=None, help="Folder to copy into (default: a temp folder)")
    args = parser.parse_args()

    report: dict = {}
    work = Path(tempfile.mkdtemp(prefix="pladaz-perf-"))
    dest_root = args.dest or (work / "dest")
    try:
        if args.exe.exists():
            report["start"] = measure_start(args.exe)
        else:
            report["start"] = {"skipped": f"{args.exe} not found"}
        aac = work / "source.m4a"
        opus = work / "source.webm"
        _make_source(args.ffmpeg, aac, ["-c:a", "aac", "-b:a", "128k"])
        _make_source(args.ffmpeg, opus, ["-c:a", "libopus", "-b:a", "160k"])
        report["post_download"] = [
            measure_post_download(args.ffmpeg, AudioProcessMode.REMUX_AAC, aac, dest_root, work),
            measure_post_download(args.ffmpeg, AudioProcessMode.ENCODE_AAC_LC, opus, dest_root, work),
        ]
        report["dest"] = "temp folder on this PC" if args.dest is None else str(args.dest)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print(json.dumps(report, indent=2))
    checks = [report["start"].get("pass", True)] + [r["pass"] for r in report["post_download"]]
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
