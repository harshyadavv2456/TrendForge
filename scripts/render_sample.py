"""Generate a deterministic, zero-API-cost demonstration video for repository review."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trendforge.config import Settings
from trendforge.renderer import render_short


def main() -> int:
    settings = Settings.from_env()
    # All demo content is locally authored. No YouTube/Groq key or OAuth token is used.
    candidate = {
        "id": "trendforge-free-demo",
        "snippet": {
            "title": "Why Strong Short Videos Open a Curiosity Loop",
            "channelTitle": "TrendForge Original Demo",
            "publishedAt": "2026-10-27T00:00:00Z",
            "categoryId": "24",
            "description": "Fictional demonstration fixture; not a live YouTube trend.",
        },
        "statistics": {"viewCount": "0", "likeCount": "0", "commentCount": "0"},
        "discovery": {
            "source_kind": "demo",
            "source_label": "Offline demo fixture — not real trend data",
            "source_rank": 1,
            "region": None,
        },
    }
    scenes = [
        {
            "headline": "Start With One Question",
            "narration": (
                "A strong short does not need a dozen ideas. It needs one clear question that makes a viewer "
                "curious enough to stay. The opening promises an answer, and every next scene earns that attention."
            ),
            "visual": "One question opens a loop; each scene adds one useful piece of the answer.",
        },
        {
            "headline": "Make The Stakes Visible",
            "narration": (
                "Next, show what makes the question interesting. A constraint, a surprising comparison, or a real "
                "trade off gives the story shape. Keep the words simple and let the graphic explain one thing at a time."
            ),
            "visual": "A simple constraint turns a broad topic into a story with direction.",
        },
        {
            "headline": "Deliver A Real Payoff",
            "narration": (
                "Do not stretch the setup just to delay the answer. Give viewers the insight you promised, then add "
                "a practical takeaway they can remember. Retention should come from value, not confusion or fake suspense."
            ),
            "visual": "Close the original loop, then add a useful lesson instead of an empty cliffhanger.",
        },
        {
            "headline": "Leave One Clear Idea",
            "narration": (
                "Finally, end on one sentence worth repeating. The best structure is simple: question, evidence, answer, "
                "lesson. This demo uses original graphics and local synthetic narration, with no borrowed footage or paid API calls."
            ),
            "visual": "Question → evidence → answer → lesson: a repeatable structure, not a copied video.",
        },
    ]
    total_words = sum(len(scene["narration"].split()) for scene in scenes)
    if not 95 <= total_words <= 155:
        raise SystemExit(f"Demo narration has {total_words} words; expected 95–155.")
    script = {
        "title": "Why Strong Shorts Open a Curiosity Loop",
        "angle": "A four-part storytelling structure that gives a short a clear promise and a real payoff.",
        "quality_score": 100,
        "narration_disclosure": "Illustrative demo script; local Piper neural synthetic narration.",
        "scenes": scenes,
        "tags": ["short form storytelling", "video structure", "creator tips"],
        "hashtags": ["#Shorts", "#Storytelling", "#CreatorTips"],
        "description": "An original TrendForge quality demo. This is illustrative content, not a report on live YouTube trends.",
        "source": {"url": ""},
        "word_count": total_words,
    }
    rendered = render_short(settings, candidate, script)
    target = ROOT / "assets" / "sample" / "trendforge-free-demo.mp4"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(rendered["path"], target)
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type,width,height",
            "-show_entries", "format=duration,size",
            "-of", "json", str(target),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    metadata = json.loads(probe.stdout)
    video = next((s for s in metadata.get("streams", []) if s.get("codec_type") == "video"), {})
    duration = float((metadata.get("format") or {}).get("duration", 0))
    size_bytes = int((metadata.get("format") or {}).get("size", 0))
    if video.get("width") != 1080 or video.get("height") != 1920:
        raise SystemExit(f"Unexpected video resolution: {video.get('width')}x{video.get('height')}")
    if not 12 <= duration <= 175 or size_bytes < 100_000:
        raise SystemExit(f"Invalid demo video duration/size: {duration}s / {size_bytes} bytes")
    print(f"Demo created: {target.relative_to(ROOT)}")
    print(f"Resolution: {video['width']}x{video['height']}; duration: {duration:.1f}s; size: {size_bytes:,} bytes")
    print("Paid/AI provider APIs used: none. Narration: local Piper neural TTS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
