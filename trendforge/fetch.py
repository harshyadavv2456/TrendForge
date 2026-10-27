"""Fetch a source video file from a YouTube watch URL or direct HTTPS media URL.

When a YouTube watch URL is supplied and yt-dlp is available, the video is
downloaded to a local file so the clipper can process it.  This is intended
only for footage you own or for which you hold reuse rights.  The clipper's
rights-confirmation gate still applies.
"""
from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .clipper import download_source, _validate_public_https_url, ClipError

LOG = logging.getLogger("trendforge.fetch")


def _download_with_ytdlp(url: str, destination: Path, *, rights_confirmed: bool) -> Path:
    if not rights_confirmed:
        raise ClipError("Rights confirmation is required before downloading or transforming source footage.")
    ytdlp = shutil.which("yt-dlp") or shutil.which("youtube-dl")
    if not ytdlp:
        raise ClipError(
            "yt-dlp is not installed. Install it (pip install yt-dlp) and retry, "
            "or supply a direct HTTPS media-file URL."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ytdlp,
        "--no-check-certificates",
        "--no-warnings",
        "--quiet",
        "--no-playlist",
        "-o", str(destination),
        url,
    ]
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired as exc:
        raise ClipError("yt-dlp download timed out.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "")[-800:]
        raise ClipError(f"yt-dlp failed: {detail}") from exc
    if not destination.exists() or destination.stat().st_size < 100_000:
        raise ClipError("yt-dlp produced no usable file.")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="TrendForge source-video fetcher (direct URL or yt-dlp fallback)")
    parser.add_argument("url", help="YouTube watch URL or direct HTTPS media-file URL")
    parser.add_argument("--output", type=Path, default=Path("outputs/source/source-video.mp4"))
    parser.add_argument("--rights-confirmed", action="store_true", default=False)
    args = parser.parse_args()
    if not args.rights_confirmed:
        parser.error("Set --rights-confirmed after verifying reuse rights.")
    try:
        url = args.url.strip()
        if "youtube.com/" in url or "youtu.be/" in url:
            LOG.info("YouTube URL detected; attempting yt-dlp download.")
            path = _download_with_ytdlp(url, args.output, rights_confirmed=args.rights_confirmed)
            print(f"Downloaded source to {path}")
        else:
            _validate_public_https_url(url)
            path = download_source(url, args.output, rights_confirmed=args.rights_confirmed)
            print(f"Downloaded source to {path}")
    except ClipError as exc:
        LOG.error("TrendForge fetch failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
