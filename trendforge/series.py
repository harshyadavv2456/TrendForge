"""Build a connected series episode from sequential source segments.

Instead of scattered highlight clips, this mode takes back-to-back segments
from the source video, separates them with "PART N / M" title cards, and
concatenates everything into a single vertical 9:16 series episode.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .clipper import ClipCandidate, _probe, _run, render_clip

LOG = logging.getLogger("trendforge.series")

WIDTH, HEIGHT = 1080, 1920

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
    """Render a vertical title card video: 'PART N / M' plus a subtitle line."""
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
            "-c:v", "libx264", "-t", str(duration), "-pix_fmt", "yuv420p",
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
    output: Path,
    *,
    title: str,
    creator: str,
    source_url: str,
    segment_seconds: int = 60,
    count: int = 5,
    title_card_seconds: float = 3.0,
) -> dict[str, Any]:
    """Render sequential source segments as one connected series episode."""
    output.parent.mkdir(parents=True, exist_ok=True)
    workdir = output.parent / ".work"
    workdir.mkdir(parents=True, exist_ok=True)

    metadata = _probe(source)
    duration = float(metadata["duration_seconds"])

    # Sequential, back-to-back segments so the episode flows continuously.
    segments: list[tuple[float, float]] = []
    start = 0.0
    for _ in range(count):
        seg_end = min(duration, start + segment_seconds)
        if seg_end - start < 10:
            break
        segments.append((start, seg_end))
        start = seg_end
        if start >= duration:
            break

    if not segments:
        raise ValueError("Source video is too short to build a series episode.")

    parts: list[Path] = []
    for index, (seg_start, seg_end) in enumerate(segments, start=1):
        clip_path = workdir / f"segment-{index:02d}.mp4"
        candidate = ClipCandidate(seg_start, seg_end, 0.0, "", 0)
        render_clip(
            source, candidate, [], clip_path,
            creator, title, source_url,
        )
        parts.append(clip_path)

        # Title card between segments (not after the last one).
        if index < len(segments):
            card_path = workdir / f"card-{index:02d}.mp4"
            _make_title_card(index, len(segments), title, card_path, duration=title_card_seconds)
            parts.append(card_path)

    # Concatenate all segments + title cards into a single episode.
    concat_list = workdir / "concat.txt"
    lines = [f"file '{p.as_posix()}'" for p in parts]
    concat_list.write_text("\n".join(lines) + "\n", encoding="utf-8")

    _run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c", "copy", str(output),
        ],
        "Series concatenation",
        timeout=300,
    )

    probe = _probe(output)
    return {
        "path": str(output),
        "duration_seconds": probe["duration_seconds"],
        "size_bytes": output.stat().st_size,
        "segments": len(segments),
        "segment_seconds": segment_seconds,
        "source_url": source_url,
        "source_creator": creator,
        "source_title": title,
        "contains_original_source_footage": True,
    }


def main() -> int:
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Build a connected series episode from sequential source footage.")
    parser.add_argument("--input", type=Path, required=True, help="Source video file")
    parser.add_argument("--output", type=Path, default=Path("outputs/series/series-episode.mp4"))
    parser.add_argument("--source-url", required=True, help="Canonical YouTube/source page URL")
    parser.add_argument("--title", required=True, help="Source video title")
    parser.add_argument("--creator", required=True, help="Source creator/channel name")
    parser.add_argument("--rights-confirmed", action="store_true", required=True, help="Confirm reuse rights")
    parser.add_argument("--count", type=int, default=5, help="Number of segments in the series")
    parser.add_argument("--segment-seconds", type=int, default=60, help="Seconds per segment")
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
            args.output.expanduser().resolve(),
            title=args.title,
            creator=args.creator,
            source_url=args.source_url,
            segment_seconds=args.segment_seconds,
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
