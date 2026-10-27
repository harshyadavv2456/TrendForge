"""Discovery provenance helpers.

YouTube API policies restrict custom derived metrics and cross-channel performance
scoring. TrendForge keeps YouTube's native ordering and attaches only the source
that supplied each candidate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def annotate_discovery(
    video: dict[str, Any],
    source_kind: str,
    source_label: str,
    source_rank: int,
    region: str | None = None,
) -> dict[str, Any]:
    """Attach native API source and rank; do not derive new performance metrics."""
    video["discovery"] = {
        "source_kind": source_kind,
        "source_label": source_label[:160],
        "source_rank": max(1, int(source_rank)),
        "region": region,
    }
    return video
