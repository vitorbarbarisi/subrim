#!/usr/bin/env python3
"""
Periodic screenshoter for macOS with crop-and-scale for R36S

- Captures the screen every N seconds for a given duration (default: 5s for 60s)
- Crops the central area by a percentage (default: 30%)
- Produces images sized for R36S compatibility (default: 640x480) using
  letterboxing to preserve aspect ratio

Examples:
  python3 screenshoter.py
  python3 screenshoter.py --interval 5 --duration 60 --outdir screenshots \
    --crop-percent 30 --target-width 640 --target-height 480
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import time
from typing import Tuple

try:
    from PIL import Image
except Exception as _exc:  # noqa: BLE001
    Image = None  # type: ignore[assignment]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Take periodic screenshots using macOS screencapture")
    parser.add_argument(
        "directory",
        nargs="?",
        default=None,
        help="Optional directory name inside local 'assets' to auto-find *_secs_base.txt and save output in that folder (e.g., 'flipper')",
    )
    parser.add_argument(
        "--base-file",
        type=str,
        default=None,
        help="Optional path to a *_base.txt file (TSV) with seconds in the second column; if provided, screenshots are taken at those timestamps instead of at a fixed interval",
    )
    parser.add_argument(
        "--offset-seconds",
        type=float,
        default=0.0,
        help="Time offset added to each timestamp read from --base-file (can be negative) to synchronize with current playback position",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Interval between screenshots in seconds (default: 5)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="Total duration to run in seconds (default: 60)",
    )
    parser.add_argument(
        "--outdir",
        type=str,
        default="screenshots",
        help="Output directory to save screenshots (default: screenshots)",
    )
    parser.add_argument(
        "--crop-percent",
        type=float,
        default=30.0,
        help="Percentage to crop from each dimension (central crop). 30 keeps 70% (default: 30)",
    )
    parser.add_argument(
        "--target-width",
        type=int,
        default=640,
        help="Target output width in pixels (default: 640)",
    )
    parser.add_argument(
        "--target-height",
        type=int,
        default=480,
        help="Target output height in pixels (default: 480)",
    )
    return parser.parse_args(argv)


def ensure_output_directory(directory_path: Path) -> None:
    directory_path.mkdir(parents=True, exist_ok=True)


def generate_filename(output_dir: Path, sequence_index: int) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return output_dir / f"screenshot_{sequence_index:03d}_{timestamp}.png"


def countdown(seconds: int = 5) -> None:
    if seconds <= 0:
        return
    for remaining in range(seconds, 0, -1):
        try:
            print(f"Iniciando em {remaining}…")
        except Exception:
            pass
        time.sleep(1.0)
    print(f"Agora!")

def take_screenshot(destination_path: Path) -> None:
    completed = subprocess.run(
        ["screencapture", "-x", str(destination_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"screencapture failed: {completed.stderr.strip() or completed.stdout.strip()}")


def compute_central_crop_box(width: int, height: int, crop_percent: float) -> Tuple[int, int, int, int]:
    if crop_percent < 0:
        crop_percent = 0.0
    if crop_percent > 90:
        crop_percent = 90.0  # prevent degenerate tiny region
    keep_ratio = 1.0 - (crop_percent / 100.0)
    new_w = int(width * keep_ratio)
    new_h = int(height * keep_ratio)
    left = (width - new_w) // 2
    top = (height - new_h) // 2
    right = left + new_w
    bottom = top + new_h
    return left, top, right, bottom


def letterbox_resize(image: Image.Image, target_w: int, target_h: int) -> Image.Image:  # type: ignore[name-defined]
    src_w, src_h = image.size
    if src_w == 0 or src_h == 0 or target_w <= 0 or target_h <= 0:
        return image
    scale = min(target_w / src_w, target_h / src_h)
    new_w = max(1, int(src_w * scale))
    new_h = max(1, int(src_h * scale))
    resized = image.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGB", (target_w, target_h), (0, 0, 0))
    x = (target_w - new_w) // 2
    y = (target_h - new_h) // 2
    canvas.paste(resized, (x, y))
    return canvas


def crop_and_scale_inplace(path: Path, crop_percent: float, target_w: int, target_h: int) -> None:
    if Image is None:
        raise RuntimeError("Pillow is required. Install with: pip install pillow")
    with Image.open(path) as im:
        im = im.convert("RGB")
        box = compute_central_crop_box(im.width, im.height, crop_percent)
        cropped = im.crop(box)
        final_img = letterbox_resize(cropped, target_w, target_h)
        final_img.save(path, format="PNG", optimize=True)


def run_scheduler(interval_seconds: float, total_duration_seconds: float, output_dir: Path, crop_percent: float, target_w: int, target_h: int) -> int:
    if interval_seconds <= 0:
        print("Interval must be positive.", file=sys.stderr)
        return 2
    if total_duration_seconds <= 0:
        print("Duration must be positive.", file=sys.stderr)
        return 2
    if Image is None:
        print("Pillow not installed. Run: pip install pillow", file=sys.stderr)
        return 2

    ensure_output_directory(output_dir)

    # Pre-start 5s countdown
    countdown(5)

    start_time = time.monotonic()
    next_fire_time = start_time
    end_time = start_time + total_duration_seconds
    sequence_index = 0

    while True:
        now = time.monotonic()
        if now >= end_time:
            break

        if now < next_fire_time:
            time.sleep(next_fire_time - now)
            now = time.monotonic()

        destination = generate_filename(output_dir, sequence_index)
        try:
            take_screenshot(destination)
            crop_and_scale_inplace(destination, crop_percent=crop_percent, target_w=target_w, target_h=target_h)
        except Exception as exc:  # noqa: BLE001 - surface error and exit
            print(f"Error taking screenshot: {exc}", file=sys.stderr)
            return 1

        sequence_index += 1
        next_fire_time += interval_seconds

    return 0


def _parse_seconds_field(field_text: str) -> float | None:
    """Parse a field like '186.645s' to float seconds. Returns None if unparsable.

    Accepts integers and decimals, requires trailing 's' (case-insensitive).
    """
    if not field_text:
        return None
    value = field_text.strip().lower()
    if not value.endswith("s"):
        return None
    numeric = value[:-1]
    try:
        return float(numeric)
    except Exception:
        return None


def load_schedule_from_base_file(base_file_path: Path) -> list[tuple[int, float]]:
    """Read a TSV base file and return a list of (index, seconds).

    Expected layout per line: index<TAB>seconds<TAB>...
    Falls back to scanning fields to find the first seconds-shaped value.
    Lines that cannot be parsed are skipped.
    """
    lines = base_file_path.read_text(encoding="utf-8").splitlines()
    schedule: list[tuple[int, float]] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if not parts:
            continue
        # Try to parse index (first column)
        try:
            idx = int(parts[0].strip())
        except Exception:
            # If no leading index, use running length + 1 later
            idx = len(schedule) + 1
        # Prefer the second column as seconds
        seconds_value: float | None = None
        if len(parts) >= 2:
            seconds_value = _parse_seconds_field(parts[1])
        if seconds_value is None:
            # Fallback: find the first seconds-shaped field
            for field in parts:
                seconds_value = _parse_seconds_field(field)
                if seconds_value is not None:
                    break
        if seconds_value is None:
            continue
        schedule.append((idx, seconds_value))
    return schedule


def run_from_base_file(
    base_file: Path,
    offset_seconds: float,
    output_dir: Path,
    crop_percent: float,
    target_w: int,
    target_h: int,
) -> int:
    if Image is None:
        print("Pillow not installed. Run: pip install pillow", file=sys.stderr)
        return 2

    if not base_file.exists() or not base_file.is_file():
        print(f"Base file not found: {base_file}", file=sys.stderr)
        return 2

    ensure_output_directory(output_dir)

    try:
        schedule = load_schedule_from_base_file(base_file)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to read base file: {exc}", file=sys.stderr)
        return 2

    if not schedule:
        print("No valid timestamps found in base file.", file=sys.stderr)
        return 2

    # Pre-start 5s countdown
    countdown(5)

    start_monotonic = time.monotonic()
    sequence_index = 0

    for idx_value, seconds_value in schedule:
        fire_time = start_monotonic + seconds_value + offset_seconds
        now = time.monotonic()
        if fire_time > now:
            time.sleep(fire_time - now)
        # Name screenshot file exactly as the base index (e.g., 1.png)
        safe_index = idx_value if idx_value > 0 else (sequence_index + 1)
        destination = output_dir / f"{safe_index}.png"
        try:
            take_screenshot(destination)
            crop_and_scale_inplace(destination, crop_percent=crop_percent, target_w=target_w, target_h=target_h)
        except Exception as exc:  # noqa: BLE001
            print(f"Error taking screenshot at {seconds_value:.3f}s (idx {idx_value}): {exc}", file=sys.stderr)
            return 1
        sequence_index += 1

    return 0


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    # Auto mode via positional 'directory'
    assets_root = Path(__file__).resolve().parent / "assets"
    if args.directory:
        base_dir = (assets_root / args.directory).resolve()
        if not base_dir.exists() or not base_dir.is_dir():
            print(f"Erro: diretório dentro de 'assets' não encontrado: {base_dir}", file=sys.stderr)
            return 1
        # Find one *_zht_secs_base.txt (prefer) or any *_secs_base.txt
        candidates = list(base_dir.rglob("*_zht_secs_base.txt"))
        if not candidates:
            candidates = list(base_dir.rglob("*_secs_base.txt"))
        if not candidates:
            print("Erro: *_secs_base.txt não encontrado no diretório informado", file=sys.stderr)
            return 1
        # Deterministic pick: first by name
        base_file_path = sorted(candidates)[0]
        output_dir = base_dir
        return run_from_base_file(
            base_file=base_file_path,
            offset_seconds=args.offset_seconds,
            output_dir=output_dir,
            crop_percent=args.crop_percent,
            target_w=args.target_width,
            target_h=args.target_height,
        )

    output_dir = Path(args.outdir).resolve()
    # If --base-file is provided, run timestamp-driven mode; otherwise periodic mode
    if args.base_file:
        return run_from_base_file(
            base_file=Path(args.base_file).resolve(),
            offset_seconds=args.offset_seconds,
            output_dir=output_dir,
            crop_percent=args.crop_percent,
            target_w=args.target_width,
            target_h=args.target_height,
        )
    else:
        return run_scheduler(
            args.interval,
            args.duration,
            output_dir,
            args.crop_percent,
            args.target_width,
            args.target_height,
        )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


