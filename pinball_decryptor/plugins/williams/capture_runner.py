"""Standalone CLI runner for the Williams PinMAME runtime-capture pipeline.

Use this to test the capture pipeline without going through the GUI:

    python -m pinball_decryptor.plugins.williams.capture_runner \\
        <path-to-rom.zip> <output-dir> [--seconds 180]

The capture pipeline spawns PinMAME under libpinmame, runs attract
mode for the requested duration, segments the captured DMD stream
into individual cinematics by detecting blank-gap / hard-cut frame
boundaries, and emits one MP4 (with matching audio) per cinematic
plus a ``capture_summary.txt``.

GUI wiring for this mode is queued — for now, test from the CLI.
"""

import argparse
import os
import sys

from .capture_pipeline import CapturePipeline


def _log(text, level="info"):
    color = {
        "info": "",
        "success": "\033[92m",
        "warning": "\033[93m",
        "error": "\033[91m",
    }.get(level, "")
    reset = "\033[0m" if color else ""
    sys.stdout.write(f"{color}[{level}] {text}{reset}\n")
    sys.stdout.flush()


def _phase(idx):
    _log(f"=== phase {idx} ===", "info")


def _progress(cur, total, desc=""):
    pct = (cur / total * 100.0) if total else 0.0
    sys.stdout.write(f"\r  [{pct:5.1f}%] {desc}\033[K")
    sys.stdout.flush()
    if cur >= total:
        sys.stdout.write("\n")


def _done(ok, summary):
    sys.stdout.write("\n")
    _log(f"done ok={ok}", "success" if ok else "error")
    print(summary)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Williams PinMAME runtime-capture pipeline runner.")
    p.add_argument("rom_zip", help="Path to MAME ROM zip (e.g. ft_l5.zip).")
    p.add_argument("output_dir", help="Directory to write clip MP4s into.")
    p.add_argument(
        "--seconds", type=float, default=180.0,
        help="Capture duration in seconds (default: 180).")
    p.add_argument(
        "--no-gameplay", action="store_true",
        help="Don't simulate a player — just capture attract mode.")
    args = p.parse_args(argv)

    if not os.path.isfile(args.rom_zip):
        p.error(f"ROM zip not found: {args.rom_zip}")
    os.makedirs(args.output_dir, exist_ok=True)

    pipe = CapturePipeline(
        args.rom_zip, args.output_dir,
        log_cb=_log, phase_cb=_phase,
        progress_cb=_progress, done_cb=_done,
        duration_seconds=args.seconds,
        simulate_gameplay=not args.no_gameplay,
    )
    pipe.run()


if __name__ == "__main__":
    main()
