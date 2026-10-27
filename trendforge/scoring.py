"""Deterministic opportunity scoring from observable public metadata."""
from __future__ import annotations

import math
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


def score_video(
    video: dict[str, Any],
    previous: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Add trend and commercial-fit heuristics; neither predicts actual views or revenue."""
    now = now or datetime.now(timezone.utc)
    snippet = video.get("snippet", {})
    stats = video.get("statistics", {})
    published = parse_time(snippet.get("publishedAt"))
    age_hours = max(0.25, (now - published).total_seconds() / 3600.0)
    views = max(0, int(stats.get("viewCount", 0) or 0))
    likes = max(0, int(stats.get("likeCount", 0) or 0))
    comments = max(0, int(stats.get("commentCount", 0) or 0))

    velocity = views / age_hours
    if previous:
        prev_views = max(0, int(previous.get("view_count", 0) or 0))
        prev_time = parse_time(previous.get("last_seen"))
        elapsed = max(0.25, (now - prev_time).total_seconds() / 3600.0)
        if views >= prev_views and prev_views > 0:
            velocity = max(velocity, (views - prev_views) / elapsed)

    freshness = 100.0 * math.exp(-age_hours / 72.0)
    velocity_score = min(100.0, math.log10(max(0.0, velocity) + 1.0) * 12.0)
    view_strength = min(100.0, math.log10(views + 1.0) * 12.0)
    engagement_rate = ((likes + comments) / max(1, views)) * 100.0
    engagement_score = min(100.0, engagement_rate * 18.0)
    title = str(snippet.get("title", "")).lower()
    category_id = str(snippet.get("categoryId", ""))

    high_value_terms = (
        "challenge", "creator", "business", "ai", "technology", "tech", "money",
        "entrepreneur", "experiment", "gaming", "science", "review", "strategy",
        "record", "building", "million", "surprise", "world's", "worlds",
    )
    topic_fit = min(100.0, 38.0 + sum(10 for term in high_value_terms if term in title))
    if category_id in {"20", "22", "23", "24", "28"}:
        topic_fit = min(100.0, topic_fit + 10.0)

    # Proxy for sponsor/advertiser relevance from public title/category only.
    # It is explicitly not a measure of the creator's earnings or actual RPM.
    commercial_terms = (
        "business", "software", "technology", "tech", "ai", "finance", "money",
        "startup", "entrepreneur", "productivity", "marketing", "review", "tools",
        "creator economy", "sponsor", "camera", "gear", "investing", "saas",
    )
    commercial_fit = min(100.0, 28.0 + sum(13 for term in commercial_terms if term in title))
    if category_id in {"26", "27", "28"}:
        commercial_fit = min(100.0, commercial_fit + 15.0)

    # Region presence is a weak audience-fit signal, not proof of viewers' location.
    regions = video.get("regions", [])
    western_fit = 100.0 if "US" in regions else (82.0 if any(r in regions for r in ("GB", "CA", "AU")) else 60.0)
    score = (
        velocity_score * 0.27
        + freshness * 0.18
        + view_strength * 0.12
        + engagement_score * 0.08
        + topic_fit * 0.13
        + commercial_fit * 0.12
        + western_fit * 0.10
    )
    video["trend"] = {
        "score": round(min(100.0, max(0.0, score)), 2),
        "age_hours": round(age_hours, 2),
        "views_per_hour_estimate": round(velocity, 1),
        "freshness": round(freshness, 1),
        "engagement_rate_percent": round(engagement_rate, 3),
        "topic_fit": round(topic_fit, 1),
        "commercial_fit_proxy": round(commercial_fit, 1),
        "scoring_version": 2,
    }
    return video
