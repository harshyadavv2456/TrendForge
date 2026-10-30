"""Build connected YouTube Shorts series from sequential source segments.

Each part is its own Shorts-compliant clip (<=60s): a highlight moment
from the source video with a fast animated "PART N / M" overlay that
fades in and out during the first ~2 seconds, then the video plays
normally. Parts use scene-cut detection + transcript/heuristic scoring
to find actual watchable moments, not boring intros.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .clipper import (
    ClipCandidate,
    _probe,
    _run,
    _select_non_overlapping,
    build_candidates,
    detect_scene_cuts,
    render_clip,
    transcribe_source,
)

LOG = logging.getLogger("trendforge.series")

WIDTH, HEIGHT = 1080, 1920
SHORTS_MAX_SECONDS = 60
DEFAULT_PART_SECONDS = 55  # content seconds; overlay rides on top, no extra time
OVERLAY_START_SECONDS = 1.0  # badge appears after the hook
OVERLAY_SECONDS = 3.0        # how long the corner PART badge stays on screen

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


def _centered_x(draw: ImageDraw.ImageDraw, text: str, font: Any, cx: int) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return int(cx - (bbox[2] - bbox[0]) / 2)


def _make_part_overlay(part: int, total: int, text: str, output: Path) -> None:
    """Render a semi-transparent PART N / M badge PNG with alpha channel."""
    pad = 40
    pad = 24
    font_big = _load_font(56, bold=True)
    font_small = _load_font(1, bold=False)

    part_text = f"PART {part}/{total}"
    subtitle = ""

    # Measure text to size the badge pill.
    dummy = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    pb = dummy.textbbox((0, 0), part_text, font=font_big)
    sb = dummy.textbbox((0, 0), subtitle, font=font_small)
    badge_w = max(pb[2] - pb[0], sb[2] - sb[0]) + pad * 2
    badge_h = (pb[3] - pb[0]) + (sb[3] - sb[1]) + pad * 3

    img = Image.new("RGBA", (badge_w, badge_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")

    # Dark rounded pill background.
    draw.rounded_rectangle(
        (0, 0, badge_w, badge_h),
        radius=40,
        fill=(0, 0, 0, 150),
    )
    # Accent border.
    draw.rounded_rectangle(
        (6, 6, badge_w - 6, badge_h - 6),
        radius=36,
        outline=(255, 255, 255, 90),
        width=3,
    )

    x_big = _centered_x(draw, part_text, font_big, badge_w // 2)
    y_big = badge_h // 2 - (pb[3] - pb[0]) // 2 - 8
    draw.text((x_big, y_big), part_text, font=font_big, fill=(255, 255, 255, 255))

    x_small = _centered_x(draw, subtitle, font_small, badge_w // 2)
    y_small = y_big + (pb[3] - pb[0]) + 12
    draw.text((x_small, y_small), subtitle, font=font_small, fill=(230, 240, 250, 235))

    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output, "PNG")


def _add_part_overlay(
    segment_path: Path,
    overlay_png: Path,
    output: Path,
    part: int,
    total: int,
    title: str,
) -> None:
    """Composite a small corner PART badge from OVERLAY_START_SECONDS for OVERLAY_SECONDS.

    The badge fades in over 0.3s, holds, then fades out over 0.3s. After that
    the video plays normally with no overlay.
    """
    _run(
        [
            "ffmpeg", "-y",
            "-i", str(segment_path),
            "-loop", "1", "-framerate", "30", "-t", str(OVERLAY_START_SECONDS + OVERLAY_SECONDS + 0.5),
            "-i", str(overlay_png),
            "-filter_complex",
            (
                "[1:v]format=rgba,"
                f"fade=t=in:st={OVERLAY_START_SECONDS}:d=0.3:alpha=1,"
                f"fade=t=out:st={OVERLAY_START_SECONDS + OVERLAY_SECONDS - 0.3}:d=0.3:alpha=1[badge];"
                "[0:v][badge]overlay=W-w-40:200:eof_action=pass:enable="
                f"'between(t,{OVERLAY_START_SECONDS},{OVERLAY_START_SECONDS + OVERLAY_SECONDS})'[v]"
            ),
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
            "-c:a", "copy",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(output),
        ],
        f"Series part {part} part-overlay",
        timeout=300,
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
    overlay_seconds: float = OVERLAY_SECONDS,
    groq_api_key: str = "",
) -> dict[str, Any]:
    """Render highlight moments from source footage as individual Shorts series parts.

    Uses scene-cut detection and transcript/heuristic scoring to find actual
    watchable moments — not boring intros. Each part is a separate MP4 under
    SHORTS_MAX_SECONDS with a fast animated "PART N / M" overlay on the first
    ~2 seconds.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    workdir = output_dir / ".work"
    workdir.mkdir(parents=True, exist_ok=True)

    metadata = _probe(source)
    duration = float(metadata["duration_seconds"])

    # Detect scene changes for highlight moment selection.
    cuts = detect_scene_cuts(source, duration)

    # Optional transcript-aware scoring when Groq API key is available.
    transcript: list[Any] = []
    try:
        transcript = transcribe_source(source, groq_api_key, workdir)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("Transcription unavailable; using local scene heuristics: %s", exc)
        transcript = []

    # Build scored candidates across the whole video, then pick the best
    # non-overlapping moments — not sequential slices from the start.
    candidates = build_candidates(duration, part_seconds, transcript, cuts)
    selected = _select_non_overlapping(candidates, count)

    if not selected:
        raise ValueError("Source video has no usable highlight moments.")

    total = len(selected)
    outputs: list[dict[str, Any]] = []

    for index, candidate in enumerate(selected, start=1):
        part_stem = f"part-{index:02d}"
        raw_segment = workdir / f"{part_stem}-raw.mp4"
        overlay_png = workdir / f"{part_stem}-badge.png"
        part_path = output_dir / f"{part_stem}.mp4"

        _make_part_overlay(index, total, title, overlay_png)

        render_clip(
            source, candidate, [], raw_segment,
            creator, title, source_url,
        )

        _add_part_overlay(raw_segment, overlay_png, part_path, index, total, title)

        probe = _probe(part_path)
        if probe["duration_seconds"] > SHORTS_MAX_SECONDS + 1:
            LOG.warning(
                "Part %d is %.1fs — over the %ds Shorts cap. Trim it or lower --part-seconds.",
                index, probe["duration_seconds"], SHORTS_MAX_SECONDS,
            )
        outputs.append({
            "path": str(part_path),
            "duration_seconds": round(probe["duration_seconds"], 2),
            "size_bytes": part_path.stat().st_size,
            "part": index,
            "total": total,
            "source_start_seconds": round(candidate.start, 3),
            "source_end_seconds": round(candidate.end, 3),
            "source_url": source_url,
            "source_creator": creator,
            "source_title": title,
            "contains_original_source_footage": True,
        })

    manifest = {
        "mode": "shorts-series",
        "rights_confirmed_by_operator": True,
        "overlay_seconds": overlay_seconds,
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
    }
    (output_dir / "series-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    import argparse
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
    parser.add_argument("--overlay-seconds", type=float, default=OVERLAY_SECONDS, help="Seconds the PART badge shows")
    parser.add_argument("--groq-api-key", type=str, default="", help="Groq API key for transcript-aware ranking")
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
            overlay_seconds=args.overlay_seconds,
            groq_api_key=args.groq_api_key,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001
        LOG.error("TrendForge series build failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
