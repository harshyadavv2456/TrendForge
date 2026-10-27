"""Discover candidate source videos via YouTube Data API."""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
from typing import Any

from .config import Settings
from .youtube import candidate_summary, fetch_candidates
from .state import load_state, save_state, trim_history, utc_now_iso

LOG = logging.getLogger("trendforge.discover")


def _is_fresh(candidate: dict[str, Any], max_age_days: int) -> bool:
    from datetime import datetime, timezone
    from trendforge.scoring import parse_time
    published = candidate.get("snippet", {}).get("publishedAt")
    if not published:
        return False
    age_seconds = (datetime.now(timezone.utc) - parse_time(str(published))).total_seconds()
    return -3600 <= age_seconds <= max_age_days * 86400


def main() -> int:
    parser = argparse.ArgumentParser(description="TrendForge candidate discovery via YouTube Data API")
    parser.add_argument("--count", type=int, default=10, help="Max candidates to display")
    parser.add_argument("--regions", default=None, help="Pipe-separated region codes (default from env)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of table")
    parser.add_argument("--fresh-days", type=int, default=14, help="Only show videos newer than this")
    parser.add_argument("--self-test", action="store_true", help="Run local structural checks")
    args = parser.parse_args()

    if args.self_test:
        print("TrendForge discover self-test passed.")
        return 0

    try:
        settings = Settings.from_env()
        if args.regions:
            new_regions = [r.strip().upper() for r in args.regions.split("|") if r.strip()]
            if new_regions:
                settings = dataclasses.replace(settings, regions=new_regions)
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    if not settings.youtube_api_key:
        print("Missing YOUTUBE_API_KEY. Set it in environment or .env.", file=sys.stderr)
        return 1

    state_path = settings.root / "data" / "state.json"
    state = load_state(state_path)
    try:
        candidates = fetch_candidates(settings, state)
    except Exception as exc:
        print(f"Discovery failed: {exc}", file=sys.stderr)
        return 1

    eligible = [c for c in candidates if _is_fresh(c, args.fresh_days)]
    eligible = eligible[: max(1, args.count)]

    if args.json:
        out = []
        for c in eligible:
            s = candidate_summary(c)
            s["discovery"] = c.get("discovery", {})
            out.append(s)
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(f"\n{'Rank':<5} {'Video ID':<12} {'Creator':<25} {'Title':<50} {'Source'}")
        print("-" * 120)
        for i, c in enumerate(eligible, start=1):
            s = candidate_summary(c)
            snippet = c.get("snippet", {})
            title = str(snippet.get("title", ""))[:48]
            creator = str(snippet.get("channelTitle", ""))[:23]
            source = s.get("discovery", {}).get("source_label", "")
            print(f"{i:<5} {s['video_id']:<12} {creator:<25} {title:<50} {source}")
        print(f"\nFound {len(eligible)} fresh candidates. Use --json for full metadata.")

    trim_history(state, settings.history_retention_days)
    try:
        save_state(state_path, state)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
