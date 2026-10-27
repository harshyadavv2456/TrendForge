"""Render an original 9:16 Short from custom graphics and AI narration; no source video is copied."""
from __future__ import annotations

import hashlib
import math
import os
import re
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont

from .config import Settings


WIDTH, HEIGHT, FPS = 1080, 1920, 30
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
ACCENTS = [(41, 227, 191), (139, 114, 255), (255, 112, 112), (255, 198, 77), (87, 173, 255)]


class RenderError(RuntimeError):
    pass


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = FONT_BOLD if bold else FONT_REGULAR
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: int) -> list[str]:
    words = re.sub(r"\s+", " ", text).strip().split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if current and draw.textbbox((0, 0), trial, font=font)[2] > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def _draw_wrapped(
    draw: ImageDraw.ImageDraw, text: str, xy: tuple[int, int], font: Any,
    fill: tuple[int, int, int], max_width: int, line_spacing: int = 18, max_lines: int = 5,
) -> int:
    x, y = xy
    lines = _wrap(draw, text, font, max_width)[:max_lines]
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill, stroke_width=0)
        y += font.size + line_spacing if hasattr(font, "size") else 45
    return y


def _make_slide(
    path: Path,
    scene: dict[str, str],
    scene_index: int,
    scene_count: int,
    script: dict[str, Any],
    candidate: dict[str, Any],
) -> None:
    seed = hashlib.sha256((str(candidate.get("id", "")) + str(scene_index)).encode()).digest()
    accent = ACCENTS[seed[0] % len(ACCENTS)]
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 15, 33))
    pixels = img.load()
    top = (9 + seed[1] % 12, 15 + seed[2] % 16, 34 + seed[3] % 25)
    bottom = (19 + seed[4] % 20, 19 + seed[5] % 18, 55 + seed[6] % 36)
    for y in range(HEIGHT):
        t = y / max(1, HEIGHT - 1)
        color = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        for x in range(WIDTH):
            pixels[x, y] = color
    draw = ImageDraw.Draw(img, "RGBA")

    # Decorative abstract shapes are deliberately illustrative, not fake footage.
    draw.ellipse((750 + seed[7] % 70, 90, 1210, 550), fill=(*accent, 30))
    draw.ellipse((-170, 1140 + seed[8] % 90, 250, 1560), outline=(*accent, 95), width=8)
    draw.rounded_rectangle((72, 72, 450, 142), radius=32, fill=(255, 255, 255, 16), outline=(*accent, 170), width=2)
    draw.text((102, 88), "TRENDFORGE  /  CREATOR RADAR", font=_font(25, True), fill=(224, 232, 255, 245))

    # Progress indicator.
    left, right, ybar = 72, WIDTH - 72, 190
    draw.rounded_rectangle((left, ybar, right, ybar + 7), radius=4, fill=(255, 255, 255, 35))
    filled = left + int((right - left) * (scene_index + 1) / scene_count)
    draw.rounded_rectangle((left, ybar, filled, ybar + 7), radius=4, fill=(*accent, 235))

    draw.text((74, 270), f"INSIGHT {scene_index + 1:02d} / {scene_count:02d}", font=_font(27, True), fill=(*accent, 255))
    headline = str(scene.get("headline", "")).strip()
    y_after = _draw_wrapped(draw, headline, (72, 355), _font(84, True), (250, 251, 255), WIDTH - 144, 20, 4)

    # A compact editorial card with the visual idea selected by the model.
    card_top = max(870, y_after + 105)
    card_bottom = min(1425, card_top + 330)
    draw.rounded_rectangle((72, card_top, WIDTH - 72, card_bottom), radius=38, fill=(5, 9, 23, 145), outline=(*accent, 160), width=3)
    draw.rounded_rectangle((104, card_top + 34, 122, card_top + 106), radius=9, fill=(*accent, 255))
    draw.text((152, card_top + 33), "THE TAKEAWAY", font=_font(28, True), fill=(*accent, 255))
    _draw_wrapped(draw, str(scene.get("visual", "")), (112, card_top + 125), _font(37, False), (228, 234, 250), WIDTH - 224, 14, 4)

    # Source metadata, not an assertion about unobserved video contents.
    snippet = candidate.get("snippet", {})
    stats = candidate.get("statistics", {})
    views = int(stats.get("viewCount", 0) or 0)
    score = float(candidate.get("trend", {}).get("score", 0))
    source_title = str(snippet.get("title", "Creator trend")).strip()
    source_creator = str(snippet.get("channelTitle", "Creator")).strip()
    draw.text((74, 1510), "OBSERVED SIGNAL", font=_font(23, True), fill=(*accent, 255))
    _draw_wrapped(draw, source_creator[:65], (74, 1554), _font(34, True), (248, 249, 255), WIDTH - 148, 8, 1)
    _draw_wrapped(draw, source_title[:130], (74, 1608), _font(25, False), (200, 210, 233), WIDTH - 148, 6, 2)
    metric_text = f"{views:,} public views  •  Radar score {score:.0f}/100"
    draw.text((74, 1733), metric_text, font=_font(23, True), fill=(220, 229, 246))
    draw.text((74, 1810), "ORIGINAL COMMENTARY  •  SOURCE LINK IN DESCRIPTION", font=_font(19, True), fill=(155, 171, 205))
    img.save(path, "PNG", optimize=True)


def _clock(seconds: float) -> str:
    millis = max(0, int(round(seconds * 1000)))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _probe_duration(path: Path) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            check=True, capture_output=True, text=True, timeout=20,
        )
        duration = float(result.stdout.strip())
    except (OSError, subprocess.CalledProcessError, ValueError, subprocess.TimeoutExpired) as exc:
        raise RenderError(f"Could not inspect narration audio with ffprobe: {exc}") from exc
    if duration < 12 or duration > 175:
        raise RenderError(f"Narration duration {duration:.1f}s is outside the supported 12–175 second range.")
    return duration


def _make_subtitles(scenes: list[dict[str, str]], duration: float, path: Path) -> None:
    total_words = max(1, sum(len(s["narration"].split()) for s in scenes))
    cursor = 0.0
    blocks = []
    subtitle_index = 1
    for scene in scenes:
        scene_words = scene["narration"].split()
        scene_duration = duration * len(scene_words) / total_words
        chunks = [scene_words[i : i + 11] for i in range(0, len(scene_words), 11)]
        chunk_words = max(1, sum(len(chunk) for chunk in chunks))
        local = cursor
        for chunk in chunks:
            part_duration = scene_duration * len(chunk) / chunk_words
            start = local
            end = min(duration, local + part_duration)
            line = " ".join(chunk).replace("--", "—")
            blocks.append(f"{subtitle_index}\n{_clock(start)} --> {_clock(max(start + 0.5, end))}\n{line}\n")
            subtitle_index += 1
            local = end
        cursor += scene_duration
    path.write_text("\n".join(blocks), encoding="utf-8")


def _run(command: list[str], label: str, timeout: int = 240) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"{label} timed out.") from exc
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or exc.stdout or "")[-1800:]
        raise RenderError(f"{label} failed. FFmpeg output: {tail}") from exc


def render_short(settings: Settings, candidate: dict[str, Any], script: dict[str, Any]) -> dict[str, Any]:
    outdir = settings.root / "outputs"
    workdir = outdir / "work"
    workdir.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)
    video_id = str(candidate.get("id", "trend"))[:32]
    audio_path = workdir / f"{video_id}.mp3"
    srt_path = workdir / f"{video_id}.srt"
    concat_path = workdir / f"{video_id}-slides.txt"
    silent_path = workdir / f"{video_id}-silent.mp4"
    final_path = outdir / f"trendforge-{video_id}.mp4"
    scenes = script["scenes"]
    narration = " ".join(scene["narration"] for scene in scenes)

    # TTS sends only our original script, not other creators' video/audio.
    try:
        response = requests.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"},
            json={
                "model": settings.tts_model,
                "voice": settings.tts_voice,
                "input": narration,
                "instructions": settings.tts_instructions,
                "response_format": "mp3",
            },
            timeout=120,
        )
    except requests.RequestException as exc:
        raise RenderError(f"OpenAI text-to-speech network error: {exc}") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message", response.text[:300])
        except ValueError:
            detail = response.text[:300]
        raise RenderError(f"OpenAI text-to-speech returned HTTP {response.status_code}: {detail}")
    audio_path.write_bytes(response.content)
    duration = _probe_duration(audio_path)

    slide_paths = []
    total_words = max(1, sum(len(scene["narration"].split()) for scene in scenes))
    lines = []
    for index, scene in enumerate(scenes):
        slide_path = workdir / f"{video_id}-scene-{index + 1}.png"
        _make_slide(slide_path, scene, index, len(scenes), script, candidate)
        slide_paths.append(slide_path)
        lines.append(f"file '{slide_path.as_posix()}'")
        scene_seconds = duration * len(scene["narration"].split()) / total_words
        lines.append(f"duration {scene_seconds:.3f}")
    # FFmpeg concat demuxer needs a repeated final file to honor the previous duration.
    lines.append(f"file '{slide_paths[-1].as_posix()}'")
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _make_subtitles(scenes, duration, srt_path)

    _run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(concat_path),
            "-vf", f"fps={FPS},scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
            "-t", f"{duration:.3f}", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            str(silent_path),
        ],
        "Motion-graphic rendering",
    )
    subtitle_filter = (
        f"subtitles={srt_path.as_posix()}:force_style="
        "'FontName=DejaVu Sans,FontSize=25,PrimaryColour=&H00FFFFFF,OutlineColour=&H00101522,"
        "BorderStyle=3,Outline=3,Shadow=0,MarginV=330,Alignment=2,WrapStyle=2'"
    )
    _run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(silent_path), "-i", str(audio_path),
            "-vf", subtitle_filter,
            "-map", "0:v:0", "-map", "1:a:0", "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            "-pix_fmt", "yuv420p", str(final_path),
        ],
        "Caption and audio mux",
    )
    if not final_path.exists() or final_path.stat().st_size < 100_000:
        raise RenderError("Rendered MP4 is missing or unexpectedly small.")
    return {
        "path": final_path,
        "duration_seconds": round(duration, 2),
        "size_bytes": final_path.stat().st_size,
        "resolution": f"{WIDTH}x{HEIGHT}",
        "audio": "AI-generated narration",
        "visuals": "original motion graphics",
    }
