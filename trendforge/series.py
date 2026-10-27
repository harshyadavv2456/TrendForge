"""Build connected YouTube Shorts series from sequential source segments.

Each part is its own Shorts-compliant clip (<=60s): a "PART N / M" title card
plus a sequential source segment. Parts tell a continuous story so viewers
watch the whole series, but each part publishes as a standalone Short.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .clipper import ClipCandidate, _probe, _run, render_clip

LOG = logging.getLogger("trendforge.series")

WIDTH, HEIGHT = 1080, 1920
SHORTS_MAX_SECONDS = 60
DEFAULT_PART_SECONDS = 45  # leaves room for a ~3-4s title card under the 60s cap

# Candidate system font paths (macOS first, then Linux fallbacks)
FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _load_font(size: int, bold: bool = False) -> Any:
    paths = FONT_PATHS if bold else FONT_PATHS[1:] + [FONT_PATHS[0]]
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


def _centered_bbox(draw: ImageDraw.ImageDraw, text: str, font: Any, cx: int, cy: int) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    return int(cx - w / 2), int(cy - h / 2)


def _make_title_card(part: int, total: int, text: str, output: Path, duration: float = 3.0) -> None:
    """Render a vertical title card video: 'PART N / M' plus a subtitle line.

    Includes silent audio so the concat filter can mix it with the source
    segment without stream mismatches.
    """
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 15, 33))
    draw = ImageDraw.Draw(img)

    font_big = _load_font(110, bold=True)
    font_small = _load_font(44, bold=False)

    part_text = f"PART {part} / {total}"
    x, y = _centered_bbox(draw, part_text, font_big, WIDTH // 2, HEIGHT // 2 - 70)
    draw.text((x, y), part_text, font=font_big, fill=(255, 255, 255))

    subtitle = str(text)[:70]
    x2, y2 = _centered_bbox(draw, subtitle, font_small, WIDTH // 2, HEIGHT // 2 + 90)
    draw.text((x2, y2), subtitle, font=font_small, fill=(200, 210, 225))

    card_path = output.parent / f"{output.stem}-card-{part:02d}.png"
    img.save(card_path)

    _run(
        [
            "ffmpeg", "-y", "-loop", "1", "-i", str(card_path),
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-c:v", "libx264", "-c:a", "aac", "-t", str(duration), "-pix_fmt", "yuv420p",
            "-shortest",
            "-vf",
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
            str(output),
        ],
        f"Title card part {part}",
        timeout=120,
    )


def build_series(
    source: Path,
    output_dir: Path,
    *,
    title: str,
    creator: str,
    source_url: str,
    part_seconds: int = DEFAULT_PART_SECONDS,
    count: int = 5,
    title_card_seconds: float = 3.0,
) -> dict[str, Any]:
    """Render sequential source segments as individual Shorts series parts.

    Each part is a separate MP4 under SHORTS_MAX_SECONDS, prefixed with a
    "PART N / M" title card so the series reads as one connected story.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    workdir = output_dir / ".work"
    workdir.mkdir(parents=True, exist_ok=True)

    metadata = _probe(source)
    duration = float(metadata["duration_seconds"])

    # Sequential, back-to-back segments so the parts flow as a series.
    segments: list[tuple[float, float]] = []
    start = 0.0
    for _ in range(count):
        seg_end = min(duration, start + part_seconds)
        if seg_end - start < 10:
            break
        segments.append((start, seg_end))
        start = seg_end
        if start >= duration:
            break

    if not segments:
        raise ValueError("Source video is too short to build a series.")

    total = len(segments)
    outputs: list[dict[str, Any]] = []

    for index, (seg_start, seg_end) in enumerate(segments, start=1):
        part_stem = f"part-{index:02d}"
        part_path = output_dir / f"{part_stem}.mp4"

        # Title card + source segment must stay under the Shorts cap.
        source_segment_seconds = SHORTS_MAX_SECONDS - title_card_seconds
        actual_seg_end = min(seg_end, seg_start + source_segment_seconds)

        card_path = workdir / f"{part_stem}-card.mp4"
        _make_title_card(index, total, title, card_path, duration=title_card_seconds)

        segment_path = workdir / f"{part_stem}-segment.mp4"
        candidate = ClipCandidate(seg_start, actual_seg_end, 0.0, "", 0)
        render_clip(
            source, candidate, [], segment_path,
            creator, title, source_url,
        )

        # Concat title card + segment into one Shorts part (re-encode so
        # timestamps are continuous and total duration stays under the 60s cap).
        _run(
            [
                "ffmpeg", "-y",
                "-i", str(card_path),
                "-i", str(segment_path),
                "-filter_complex",
                "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
                "-c:a", "aac", "-b:a", "128k",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                str(part_path),
            ],
            f"Series part {index} concatenation",
            timeout=300,
        )

        probe = _probe(part_path)
        outputs.append({
            "path": str(part_path),
            "duration_seconds": probe["duration_seconds"],
            "size_bytes": part_path.stat().st_size,
            "part": index,
            "total": total,
            "source_start_seconds": round(seg_start, 3),
            "source_end_seconds": round(actual_seg_end, 3),
            "source_url": source_url,
            "source_creator": creator,
            "source_title": title,
            "contains_original_source_footage": True,
        })

    manifest = {
        "mode": "shorts-series",
        "rights_confirmed_by_operator": True,
        "source": {
            "title": title,
            "creator": creator,
            "url": source_url,
            "duration_seconds": duration,
            "width": metadata["video"].get("width"),
            "height": metadata["video"].get("height"),
        },
        "parts": outputs,
        "total_parts": total,
        "part_seconds": part_seconds,
        "title_card_seconds": title_card_seconds,
    }
    (output_dir / "series-manifest.json").write_text(
        __import__("json").dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        description="Build connected YouTube Shorts series from sequential source footage.",
    )
    parser.add_argument("--input", type=Path, required=True, help="Source video file")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/series"))
    parser.add_argument("--source-url", required=True, help="Canonical YouTube/source page URL")
    parser.add_argument("--title", required=True, help="Source video title")
    parser.add_argument("--creator", required=True, help="Source creator/channel name")
    parser.add_argument("--rights-confirmed", action="store_true", required=True, help="Confirm reuse rights")
    parser.add_argument("--count", type=int, default=5, help="Number of parts in the series")
    parser.add_argument("--part-seconds", type=int, default=DEFAULT_PART_SECONDS, help="Seconds per source segment")
    parser.add_argument("--title-card-seconds", type=float, default=3.0, help="Seconds per title card")
    args = parser.parse_args()

    if not args.rights_confirmed:
        parser.error("Set --rights-confirmed after verifying reuse rights.")
    if not args.input.is_file():
        print(f"Source video not found: {args.input}", file=sys.stderr)
        return 1

    try:
        result = build_series(
            args.input.expanduser().resolve(),
            args.output_dir.expanduser().resolve(),
            title=args.title,
            creator=args.creator,
            source_url=args.source_url,
            part_seconds=args.part_seconds,
            count=args.count,
            title_card_seconds=args.title_card_seconds,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001
        LOG.error("TrendForge series build failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
