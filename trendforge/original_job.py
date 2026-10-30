"""CI job: trending data -> one original motion-graphics Short (no downloads, no upload).

Writes outputs/release/<video_id>/{short.mp4, metadata.json} and prints the video id.
Skips sources listed in SKIP_IDS (existing clips-* release tags).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from . import youtube
from .config import Settings
from .quota import QuotaLedger
from .renderer import render_short
from .scriptwriter import ScriptGenerationError, generate_script, template_script
from .state import load_state, save_state
from .youtube import fetch_candidates

LOG = logging.getLogger("trendforge.original")
MAX_SECONDS = 59.0


def _polish(script: dict, cand: dict) -> None:
    """Enforce title < 60 chars on a word boundary, a real description, and >=3 hashtags."""
    title = " ".join(str(script.get("title", "")).split())
    if len(title) >= 60:
        title = title[:59].rsplit(" ", 1)[0].rstrip(" ,.:;-")
    script["title"] = title
    base = template_script(cand)
    tags = list(dict.fromkeys((script.get("hashtags") or []) + base["hashtags"]))[:4]
    script["hashtags"] = tags
    desc = str(script.get("description", "")).strip()
    body = desc.split("Source video and public metadata:")[0].strip()
    if len(body) < 40:
        script["description"] = base["description"]
    else:
        snippet = cand.get("snippet", {})
        script["description"] = (
            f"{body}\n\nWatch the original video by {snippet.get('channelTitle', 'the creator')}: "
            f"https://www.youtube.com/watch?v={cand.get('id')}\n"
            "Original commentary with custom motion graphics; no footage from the original is used.\n\n"
            + " ".join(tags)
        )[:4800]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.from_env()
    if not settings.youtube_api_key:
        print("YOUTUBE_API_KEY missing", file=sys.stderr)
        return 1
    state_path = settings.root / "data" / "state.json"
    state = load_state(state_path)
    skip = set(os.getenv("SKIP_IDS", "").split())
    candidates = fetch_candidates(settings, state)
    save_state(state_path, state)
    ledger = QuotaLedger(settings.root / "data" / "quota_ledger.json")
    ledger.record(youtube.UNITS_USED)
    ledger.save()
    LOG.info("Discovery used ~%s quota units; %s candidates", youtube.UNITS_USED, len(candidates))
    for cand in candidates[:6]:
        vid = str(cand.get("id", ""))
        if not vid or vid in skip:
            continue
        try:
            script = generate_script(settings, cand)
        except ScriptGenerationError as exc:
            LOG.warning("Groq script failed for %s (%s); using template script.", vid, exc)
            script = template_script(cand)
        _polish(script, cand)
        result = render_short(settings, cand, script)
        if result["duration_seconds"] > MAX_SECONDS:
            LOG.warning("Render %.1fs too long for %s; skipping", result["duration_seconds"], vid)
            continue
        out = settings.root / "outputs" / "release" / vid
        out.mkdir(parents=True, exist_ok=True)
        final = out / "short.mp4"
        os.replace(result["path"], final)
        title = script["title"]
        meta = {
            "source": script["source"],
            "clips": [{
                "file": "short.mp4", "part": 1, "total": 1,
                "duration_seconds": result["duration_seconds"], "resolution": result["resolution"],
                "title": title, "description": script["description"],
                "tags": script.get("tags", []), "hashtags": script.get("hashtags", []),
                "categoryId": settings.video_category_id, "selfDeclaredMadeForKids": False,
                "script_source": "template" if script.get("template") else "groq",
            }],
        }
        (out / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(vid)
        return 0
    LOG.info("No usable candidate this run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
