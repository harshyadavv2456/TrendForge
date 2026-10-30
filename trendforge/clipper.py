"""Create real-footage highlight clips from a rights-cleared source video.

This module never downloads a YouTube watch page. Supply a local file or a direct
HTTPS media-file URL that you are authorized to process. It uses FFmpeg for
scene detection/reframing, optionally Groq Whisper for timestamped transcription,
and Groq text ranking when available. No synthetic scenes are rendered.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import os
import re
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .config import Settings
from .publisher import upload_short

LOG = logging.getLogger("trendforge.clipper")
GROQ_BASE = "https://api.groq.com/openai/v1"
MAX_SOURCE_BYTES = 750 * 1024 * 1024
MAX_TRANSCRIPTION_BYTES = 22 * 1024 * 1024
DEFAULT_CLIP_SECONDS = 32


class ClipError(RuntimeError):
    """Raised when a source cannot safely or successfully be clipped."""


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class ClipCandidate:
    start: float
    end: float
    score: float
    transcript: str
    scene_cuts: int


def _run(command: list[str], label: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ClipError(f"{label} timed out.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "")[-1600:]
        raise ClipError(f"{label} failed: {detail}") from exc


def _validate_public_https_url(url: str) -> str:
    """Accept direct media URLs only; do not use YouTube watch/stream endpoints."""
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ClipError("Source URL must be a direct HTTPS media-file URL without embedded credentials.")
        host = parsed.hostname.rstrip(".").lower()
        blocked = ("youtube.com", "youtu.be", "youtube-nocookie.com", "googlevideo.com", "youtubei.googleapis.com")
        if any(host == domain or host.endswith("." + domain) for domain in blocked):
            raise ClipError(
                "A YouTube watch/stream URL is not a source file. Use a creator-provided master file, "
                "a video you downloaded from your own YouTube Studio, or another authorized direct media URL."
            )
        if host in {"localhost", "localhost.localdomain"}:
            raise ClipError("Private/local source hosts are not allowed.")
        try:
            literal = ipaddress.ip_address(host)
            if not literal.is_global:
                raise ClipError("Private or reserved IP addresses are not allowed as source URLs.")
        except ValueError:
            try:
                addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
            except OSError as exc:
                raise ClipError(f"Could not resolve source host: {host}") from exc
            if not addresses or any(not ipaddress.ip_address(addr.split("%", 1)[0]).is_global for addr in addresses):
                raise ClipError("Source URL resolves to a private or reserved address.")
        return url.strip()
    except ValueError as exc:
        raise ClipError("Source URL is malformed.") from exc


def download_source(url: str, destination: Path, *, rights_confirmed: bool) -> Path:
    if not rights_confirmed:
        raise ClipError("Rights confirmation is required before downloading or transforming source footage.")
    _validate_public_https_url(url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with requests.get(url, stream=True, timeout=(20, 60), allow_redirects=True) as response:
            response.raise_for_status()
            final_url = _validate_public_https_url(response.url)
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type and not (content_type.startswith("video/") or content_type in {"application/octet-stream", "binary/octet-stream"}):
                raise ClipError(f"Source URL did not return video media (Content-Type: {content_type}).")
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > MAX_SOURCE_BYTES:
                raise ClipError(f"Source exceeds the {MAX_SOURCE_BYTES // (1024 * 1024)} MB source limit.")
            with destination.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_SOURCE_BYTES:
                        raise ClipError("Source exceeds the 750 MB download limit.")
                    handle.write(chunk)
        if total < 100_000:
            raise ClipError("Downloaded source is too small to be a valid video file.")
        _probe(destination)
        LOG.info("Downloaded authorized source media (%s bytes) from %s", total, final_url.split("?", 1)[0])
        return destination
    except requests.RequestException as exc:
        destination.unlink(missing_ok=True)
        raise ClipError(f"Could not fetch direct source video: {exc}") from exc
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def _probe(path: Path) -> dict[str, Any]:
    result = _run([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,size:stream=codec_type,codec_name,width,height,duration",
        "-of", "json", str(path),
    ], "Source video probe", timeout=30)
    try:
        info = json.loads(result.stdout)
        duration = float(info["format"]["duration"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ClipError("The source file is not a readable video.") from exc
    video_streams = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    if not video_streams or duration < 12:
        raise ClipError("Source must contain video and be at least 12 seconds long.")
    info["duration_seconds"] = duration
    info["video"] = video_streams[0]
    return info


def detect_scene_cuts(source: Path, duration: float) -> list[float]:
    """Return approximate scene-cut timestamps using FFmpeg's scene detector."""
    result = _run([
        "ffmpeg", "-hide_banner", "-i", str(source), "-vf", "select='gt(scene,0.22)',showinfo",
        "-an", "-f", "null", "-",
    ], "Scene detection", timeout=300)
    cuts = []
    for match in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", result.stderr):
        value = float(match.group(1))
        if 0 < value < duration:
            cuts.append(value)
    return sorted(set(cuts))


def _extract_audio(source: Path, workdir: Path) -> list[tuple[Path, float]]:
    """Extract mp3 chunks small enough for Groq's free-tier transcription endpoint."""
    workdir.mkdir(parents=True, exist_ok=True)
    whole = workdir / "transcript-audio.mp3"
    _run([
        "ffmpeg", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
        "-b:a", "48k", "-f", "mp3", str(whole),
    ], "Audio extraction", timeout=300)
    if whole.stat().st_size <= MAX_TRANSCRIPTION_BYTES:
        return [(whole, 0.0)]
    whole.unlink(missing_ok=True)
    pattern = workdir / "transcript-part-%03d.mp3"
    _run([
        "ffmpeg", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "40k",
        "-f", "segment", "-segment_time", "240", "-reset_timestamps", "1", str(pattern),
    ], "Audio chunking", timeout=300)
    parts = sorted(workdir.glob("transcript-part-*.mp3"))
    result: list[tuple[Path, float]] = []
    offset = 0.0
    for part in parts:
        if part.stat().st_size > MAX_TRANSCRIPTION_BYTES:
            raise ClipError("An audio chunk exceeds the transcription API upload limit.")
        result.append((part, offset))
        offset += _probe_audio_duration(part)
    if not result:
        raise ClipError("Could not produce audio chunks for transcription.")
    return result


def _probe_audio_duration(path: Path) -> float:
    result = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)], "Audio probe", timeout=20)
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise ClipError("Could not determine audio chunk duration.") from exc


def transcribe_source(source: Path, api_key: str, workdir: Path, language: str = "en") -> list[TranscriptSegment]:
    if not api_key.strip():
        return []
    transcript_chunks = _extract_audio(source, workdir)
    segments: list[TranscriptSegment] = []
    for audio_path, offset in transcript_chunks:
        try:
            with audio_path.open("rb") as handle:
                response = requests.post(
                    f"{GROQ_BASE}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    data={"model": "whisper-large-v3-turbo", "response_format": "verbose_json", "language": language,
                          "timestamp_granularities[]": "segment", "temperature": "0"},
                    files={"file": (audio_path.name, handle, "audio/mpeg")},
                    timeout=(30, 240),
                )
            if response.status_code >= 400:
                raise ClipError(f"Groq transcription returned HTTP {response.status_code}: {response.text[:400]}")
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ClipError(f"Groq transcription failed for {audio_path.name}: {exc}") from exc
        for item in payload.get("segments", []) or []:
            text = re.sub(r"\s+", " ", str(item.get("text", ""))).strip()
            if not text:
                continue
            start = max(0.0, float(item.get("start", 0.0)) + offset)
            end = max(start + 0.05, float(item.get("end", start + 0.1)) + offset)
            segments.append(TranscriptSegment(start, end, text))
    return sorted(segments, key=lambda s: s.start)


_HOOK_WORDS = {
    "wait", "what", "why", "how", "secret", "insane", "crazy", "unexpected", "actually", "never",
    "finally", "impossible", "mistake", "problem", "wrong", "win", "fail", "failed", "wild", "shocking",
    "surprise", "surprised", "unbelievable", "ridiculous", "dangerous", "best", "worst", "trick", "hack",
    "free", "caught", "destroyed", "saved", "revealed", "realized", "turns", "except", "but",
}


def _window_text(segments: list[TranscriptSegment], start: float, end: float) -> str:
    return " ".join(s.text for s in segments if s.end > start and s.start < end).strip()


def _heuristic_score(text: str, start: float, end: float, scene_cuts: list[float], segments: list[TranscriptSegment]) -> float:
    length = max(1.0, end - start)
    words = re.findall(r"[\w']+", text.lower())
    density = min(1.0, len(words) / (length * 2.2))
    hooks = sum(1 for w in words if w in _HOOK_WORDS)
    punctuation = text.count("!") + text.count("?")
    cuts = sum(1 for t in scene_cuts if start <= t <= end)
    cut_density = min(1.0, cuts / max(1.0, length / 3.0))
    silence_penalty = 0.35 if not words else 0.0
    speech_alignment = sum(max(0.0, min(end, s.end) - max(start, s.start)) for s in segments) / length if segments else 0.0
    return 0.42 * density + 0.20 * min(1.0, hooks / 5.0) + 0.10 * min(1.0, punctuation / 3.0) + 0.18 * cut_density + 0.10 * min(1.0, speech_alignment) - silence_penalty


def build_candidates(duration: float, clip_seconds: int, segments: list[TranscriptSegment], scene_cuts: list[float], maximum: int = 72) -> list[ClipCandidate]:
    if not 15 <= clip_seconds <= 60:
        raise ClipError("Clip length must be between 15 and 60 seconds.")
    if duration < clip_seconds:
        clip_seconds = int(duration)
    if clip_seconds < 12:
        raise ClipError("Source is too short for a usable highlight clip.")
    latest = max(0.0, duration - clip_seconds)
    step = max(4.0, clip_seconds / 3.0)
    starts = [float(x) for x in range(0, int(latest) + 1, max(1, int(step)))]
    if latest and (not starts or latest - starts[-1] > 2.0):
        starts.append(latest)
    if len(starts) > maximum:
        indices = sorted({round(i * (len(starts) - 1) / (maximum - 1)) for i in range(maximum)})
        starts = [starts[i] for i in indices]
    candidates = []
    for start in starts:
        end = min(duration, start + clip_seconds)
        text = _window_text(segments, start, end)
        score = _heuristic_score(text, start, end, scene_cuts, segments)
        nearby_cut = any(abs(cut - start) <= 1.5 for cut in scene_cuts)
        score += 0.04 if nearby_cut else 0.0
        candidates.append(ClipCandidate(start, end, score, text, sum(start <= t <= end for t in scene_cuts)))
    return sorted(candidates, key=lambda c: c.score, reverse=True)


def rank_with_groq(candidates: list[ClipCandidate], api_key: str, model: str) -> list[ClipCandidate]:
    """Ask Groq to pick compelling, self-contained moments from transcribed windows."""
    if not api_key.strip() or not any(c.transcript for c in candidates):
        return candidates
    shortlist = candidates[: min(18, len(candidates))]
    data = [{"id": i, "start": round(c.start, 2), "end": round(c.end, 2), "heuristic": round(c.score, 4), "transcript": c.transcript[:900]} for i, c in enumerate(shortlist)]
    prompt = (
        "Choose the strongest short-form highlight segments from this transcript-window list. "
        "Score each 0-100 for immediate hook, coherent setup-payoff, surprise/emotion, and standalone clarity. "
        "Use only transcript evidence; do not infer unseen visuals. Avoid incomplete sentences, long setup, repetitive clips, "
        "and unsafe/defamatory claims. Return ONLY JSON: {\"scores\":[{\"id\":0,\"score\":0,\"reason\":\"brief\"}]}.\n"
        + json.dumps(data, ensure_ascii=False)
    )
    try:
        response = requests.post(
            f"{GROQ_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model or "openai/gpt-oss-20b", "temperature": 0.1, "max_tokens": 1000,
                  "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": "You are a careful editor who ranks authorized source-video clips."}, {"role": "user", "content": prompt}]},
            timeout=(20, 90),
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        scores = json.loads(content).get("scores", [])
        ranked = []
        for index, candidate in enumerate(shortlist):
            model_score = next((float(x.get("score", 0)) for x in scores if int(x.get("id", -1)) == index), 0.0)
            ranked.append(ClipCandidate(candidate.start, candidate.end, model_score / 100.0, candidate.transcript, candidate.scene_cuts))
        if not any(c.score > 0 for c in ranked):
            return candidates
        ranked.extend(candidates[len(shortlist):])
        return sorted(ranked, key=lambda c: c.score, reverse=True)
    except (requests.RequestException, ValueError, KeyError, TypeError, IndexError) as exc:
        LOG.warning("Groq highlight ranking unavailable; using local transcript/scene heuristics: %s", exc)
        return candidates


def _select_non_overlapping(candidates: list[ClipCandidate], count: int, min_gap: float = 4.0) -> list[ClipCandidate]:
    chosen: list[ClipCandidate] = []
    for candidate in candidates:
        if all(candidate.end + min_gap <= picked.start or candidate.start >= picked.end + min_gap for picked in chosen):
            chosen.append(candidate)
        if len(chosen) >= count:
            break
    return sorted(chosen, key=lambda c: c.start)


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, int(round(seconds * 100)))
    h, centiseconds = divmod(centiseconds, 360000)
    m, centiseconds = divmod(centiseconds, 6000)
    s, centiseconds = divmod(centiseconds, 100)
    return f"{h}:{m:02d}:{s:02d}.{centiseconds:02d}"


def write_ass_captions(segments: list[TranscriptSegment], start: float, end: float, path: Path, creator: str, title: str) -> None:
    header = [
        "[Script Info]", "Title: TrendForge source-footage clip", "ScriptType: v4.00+", "WrapStyle: 2", "ScaledBorderAndShadow: yes",
        "PlayResX: 1080", "PlayResY: 1920", "", "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        "Style: Caption,DejaVu Sans,42,&H00FFFFFF,&H0000FFFF,&H00101522,&H90060917,-1,0,0,0,100,100,0,0,3,3,0,2,72,72,430,1",
        "Style: Credit,DejaVu Sans,23,&H00FFFFFF,&H0000FFFF,&H00101522,&H90060917,-1,0,0,0,100,100,0,0,3,2,0,8,55,55,65,1",
        "", "[Events]", "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    credit = f"SOURCE: {creator[:70]} — {title[:80]}".replace("{", "").replace("}", "")
    rows = [f"Dialogue: 0,0:00:00.00,{_ass_time(end-start)},Credit,,0,0,0,,{credit}"]
    for seg in segments:
        seg_start, seg_end = max(start, seg.start), min(end, seg.end)
        text = re.sub(r"\s+", " ", seg.text).strip().replace("{", "").replace("}", "").replace("\\", "")
        if not text or seg_end <= seg_start:
            continue
        words = text.split()
        chunks = [words[i:i+7] for i in range(0, len(words), 7)]
        weight = sum(len(chunk) for chunk in chunks) or 1
        cursor = seg_start - start
        available = seg_end - seg_start
        for chunk in chunks:
            piece_duration = available * len(chunk) / weight
            chunk_end = min(end-start, cursor + piece_duration)
            caption = " ".join(chunk)
            rows.append(f"Dialogue: 1,{_ass_time(cursor)},{_ass_time(max(cursor+0.12, chunk_end))},Caption,,0,0,0,,{caption}")
            cursor = chunk_end
    path.write_text("\n".join(header + rows) + "\n", encoding="utf-8")


def _ffmpeg_has_subtitles_filter() -> bool:
    try:
        probe = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        return " subtitles " in probe.stdout or " subtitles" in probe.stdout
    except Exception:
        return False


_SUBTITLES_FILTER_AVAILABLE = _ffmpeg_has_subtitles_filter()


def _render_credit_image(path: Path, text: str, width: int = 1080, height: int = 130) -> Path:
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    y = 18
    for line in text.split("\n"):
        if not line.strip():
            continue
        bbox = draw.textbbox((0, 0), line)
        line_h = bbox[3] - bbox[1]
        draw.text((20, y), line, fill=(255, 255, 255, 245))
        y += line_h + 4
    img_path = path.parent / f"{path.stem}-credit.png"
    img.save(img_path)
    return img_path


def render_clip(source: Path, candidate: ClipCandidate, segments: list[TranscriptSegment], destination: Path,
                creator: str, title: str, source_url: str) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    workdir = destination.parent / ".work"
    workdir.mkdir(parents=True, exist_ok=True)

    inputs = [str(source)]

    if _SUBTITLES_FILTER_AVAILABLE and segments:
        subtitle_path = workdir / f"{destination.stem}.ass"
        write_ass_captions(segments, candidate.start, candidate.end, subtitle_path, creator, title)
        subtitle_arg = str(subtitle_path.resolve()).replace("\\", "/").replace(" ", "\\ ")
        vf = (
            "[0:v]split=2[bg][fg];"
            "[bg]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=10:3,scale=1080:1920[background];"
            "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[foreground];"
            f"[background][foreground]overlay=(W-w)/2:(H-h)/2,subtitles={subtitle_arg}[v]"
        )
    else:
        credit_text = f"SOURCE: {creator[:60]} — {title[:70]}".replace("{", "").replace("}", "")
        credit_path = _render_credit_image(workdir, credit_text)
        inputs.append(str(credit_path))
        vf = (
            "[0:v]split=2[bg][fg];"
            "[bg]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=10:3,scale=1080:1920[background];"
            "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[foreground];"
            "[background][foreground]overlay=(W-w)/2:(H-h)/2[base];"
            "[1:v]scale=1080:130[credit];"
            "[base][credit]overlay=0:H-h[v]"
        )

    cmd = ["ffmpeg", "-y", "-ss", f"{candidate.start:.3f}", "-i", str(source)]
    if len(inputs) > 1:
        cmd += ["-i", inputs[1]]
    duration = candidate.end - candidate.start
    cmd += [
        "-filter_complex", vf, "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
        "-threads", "2", "-c:a", "aac", "-b:a", "128k", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-t", f"{duration:.3f}", str(destination),
    ]
    _run(cmd, "Source clip rendering", timeout=360)
    probe = _probe(destination)
    if abs(float(probe["duration_seconds"]) - (candidate.end - candidate.start)) > 2.0:
        raise ClipError("Rendered clip duration does not match its selected source interval.")
    return {
        "path": str(destination), "duration_seconds": probe["duration_seconds"], "size_bytes": destination.stat().st_size,
        "source_start_seconds": round(candidate.start, 3), "source_end_seconds": round(candidate.end, 3),
        "heuristic_or_model_score": round(candidate.score, 4), "source_url": source_url,
        "source_creator": creator, "source_title": title, "contains_original_source_footage": True,
    }


def run_clipper(source: Path, output_dir: Path, *, title: str, creator: str, source_url: str,
                rights_confirmed: bool, count: int = 3, clip_seconds: int = DEFAULT_CLIP_SECONDS,
                groq_api_key: str = "", model: str = "openai/gpt-oss-20b", auto_publish: bool = False) -> list[dict[str, Any]]:
    if not rights_confirmed:
        raise ClipError("Rights confirmation is required. Do not process or republish footage without permission or a license allowing it.")
    if not source.is_file():
        raise ClipError(f"Source video file not found: {source}")
    if not title.strip() or not creator.strip() or not source_url.strip():
        raise ClipError("Source title, creator/channel, and canonical source URL are required for attribution.")
    source_url = source_url.strip()
    parsed_source = urlparse(source_url)
    source_host = (parsed_source.hostname or "").lower().rstrip(".")
    is_youtube_page = (
        parsed_source.scheme == "https"
        and (source_host == "youtube.com" or source_host.endswith(".youtube.com") or source_host == "youtu.be" or source_host.endswith(".youtu.be"))
    )
    if not is_youtube_page:
        _validate_public_https_url(source_url)
    metadata = _probe(source)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="trendforge-clipper-") as temp:
        workdir = Path(temp)
        cuts = detect_scene_cuts(source, float(metadata["duration_seconds"]))
        try:
            transcript = transcribe_source(source, groq_api_key, workdir, os.getenv("CLIP_LANGUAGE", "en"))
        except ClipError as exc:
            LOG.warning("Transcription unavailable; continuing with local scene heuristics: %s", exc)
            transcript = []
        candidates = build_candidates(float(metadata["duration_seconds"]), clip_seconds, transcript, cuts)
        ranked = rank_with_groq(candidates, groq_api_key, model)
        selected = _select_non_overlapping(ranked, max(1, count))
        if not selected:
            raise ClipError("No valid clip windows were found.")
        outputs = []
        for index, candidate in enumerate(selected, start=1):
            path = output_dir / f"clip-{index:02d}.mp4"
            result = render_clip(source, candidate, transcript, path, creator, title, source_url)
            result["transcript"] = candidate.transcript
            result["score_reason"] = "Groq transcript ranking" if groq_api_key and candidate.transcript else "local speech-density and scene-change heuristic"
            outputs.append(result)
        manifest = {
            "mode": "real-source-footage-clipping", "rights_confirmed_by_operator": True,
            "source": {"title": title, "creator": creator, "url": source_url, "duration_seconds": metadata["duration_seconds"],
                       "width": metadata["video"].get("width"), "height": metadata["video"].get("height")},
            "clips": outputs,
            "limitations": ["Automated ranking is a heuristic, even with transcript ranking; review clips before publication.",
                            "Rights confirmation is supplied by the operator and is not independently verified."],
        }
        (output_dir / "clip-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if auto_publish:
        settings = Settings.from_env()
        missing = [name for name, value in (("YOUTUBE_CLIENT_ID", settings.youtube_client_id), ("YOUTUBE_CLIENT_SECRET", settings.youtube_client_secret), ("YOUTUBE_REFRESH_TOKEN", settings.youtube_refresh_token)) if not value]
        if missing:
            raise ClipError("CLIP_AUTO_PUBLISH requested, but missing OAuth config: " + ", ".join(missing))
        for result in outputs:
            clip_number = Path(result["path"]).stem
            script = {
                "title": (f"{title} | {clip_number.replace('-', ' ').title()}"[:95]),
                "description": (
                    f"A highlight clip from {creator}: {title}.\n\nOriginal source: {source_url}\n"
                    "Footage used with permission/license as confirmed by the uploader. Contact the source creator for full context."
                )[:4800],
                "tags": ["shorts", "highlight", "clip", creator[:40]],
                "source": {"url": source_url, "creator": creator, "title": title},
            }
            from .quota import UPLOAD_UNITS, QuotaLedger
            from .publisher import QuotaExceededError
            ledger = QuotaLedger(settings.root / "data" / "quota_ledger.json", max_uploads_per_day=settings.max_uploads_per_day)
            block = ledger.upload_block_reason()
            if block:
                LOG.warning("Clip upload skipped: %s", block)
                break
            try:
                result["upload"] = upload_short(settings, Path(result["path"]), script, publish=True)
                ledger.record(UPLOAD_UNITS, uploads=1)
            except QuotaExceededError as exc:
                ledger.record(UPLOAD_UNITS)
                ledger.mark_exhausted(str(exc))
                ledger.save()
                LOG.error("Quota hit; stopping uploads: %s", exc)
                break
            ledger.save()
        (output_dir / "clip-manifest.json").write_text(json.dumps({"mode": "real-source-footage-clipping", "source_url": source_url, "clips": outputs}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Clip real highlight scenes from a rights-cleared source video.")
    parser.add_argument("--input", type=Path, help="Local source video. If omitted, SOURCE_MEDIA_URL is downloaded.")
    parser.add_argument("--source-url", default=os.getenv("SOURCE_VIDEO_URL", ""), help="Canonical public source page (not a media downloader URL).")
    parser.add_argument("--title", default=os.getenv("SOURCE_VIDEO_TITLE", ""))
    parser.add_argument("--creator", default=os.getenv("SOURCE_VIDEO_CREATOR", ""))
    parser.add_argument("--rights-confirmed", action="store_true", default=os.getenv("SOURCE_RIGHTS_CONFIRMED", "false").lower() == "true")
    parser.add_argument("--count", type=int, default=int(os.getenv("CLIP_COUNT", "3")))
    parser.add_argument("--seconds", type=int, default=int(os.getenv("CLIP_SECONDS", str(DEFAULT_CLIP_SECONDS))))
    parser.add_argument("--publish", action="store_true", default=os.getenv("CLIP_AUTO_PUBLISH", "false").lower() == "true")
    parser.add_argument("--output", type=Path, default=Path("outputs/clips"))
    args = parser.parse_args()
    if not args.rights_confirmed:
        parser.error("Set SOURCE_RIGHTS_CONFIRMED=true or pass --rights-confirmed after verifying reuse rights.")
    try:
        if args.input:
            source = args.input.expanduser().resolve()
        else:
            source_url = _validate_public_https_url(os.getenv("SOURCE_MEDIA_URL", ""))
            source = Path("outputs/source/source-video").with_suffix(_extension_from_url(source_url))
            download_source(source_url, source, rights_confirmed=args.rights_confirmed)
        source_page = args.source_url.strip()
        if not source_page:
            raise ClipError("Pass --source-url with the canonical video page for source attribution.")
        outputs = run_clipper(
            source, args.output, title=args.title, creator=args.creator, source_url=source_page,
            rights_confirmed=args.rights_confirmed, count=args.count, clip_seconds=args.seconds,
            groq_api_key=os.getenv("GROQ_API_KEY", ""), model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
            auto_publish=args.publish,
        )
        print(json.dumps(outputs, indent=2, ensure_ascii=False))
        return 0
    except (ClipError, OSError, ValueError) as exc:
        LOG.error("TrendForge clipper failed: %s", exc)
        return 1


def _extension_from_url(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in (".mp4", ".mov", ".mkv", ".webm", ".m4v"):
        if path.endswith(ext):
            return ext
    return ".mp4"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
