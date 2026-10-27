"""YouTube Data API discovery. Only public metadata is fetched; media is never downloaded."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import requests

from .config import Settings
from .scoring import parse_time, score_video
from .state import utc_now_iso

API = "https://www.googleapis.com/youtube/v3"
TIMEOUT = 25


class YouTubeAPIError(RuntimeError):
    pass


def _get(settings: Settings, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    query = dict(params)
    query["key"] = settings.youtube_api_key
    try:
        response = requests.get(f"{API}/{endpoint}", params=query, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise YouTubeAPIError(f"YouTube API network error for {endpoint}: {exc}") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message", response.text[:300])
        except ValueError:
            detail = response.text[:300]
        if response.status_code == 403:
            detail = f"{detail}. Check YouTube Data API quota, API key restrictions, and whether YouTube Data API v3 is enabled."
        raise YouTubeAPIError(f"YouTube API {endpoint} returned HTTP {response.status_code}: {detail}")
    try:
        return response.json()
    except ValueError as exc:
        raise YouTubeAPIError(f"YouTube API {endpoint} returned invalid JSON") from exc


def _add_region(mapping: dict[str, set[str]], video_id: str, region: str) -> None:
    mapping.setdefault(video_id, set()).add(region)


def fetch_candidates(settings: Settings, state: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch popular charts across regions plus a quota-limited rotating recent-query set."""
    region_presence: dict[str, set[str]] = {}
    ids: set[str] = set()
    now = datetime.now(timezone.utc)

    for region in settings.regions:
        payload = _get(
            settings,
            "videos",
            {
                "part": "snippet,statistics,contentDetails",
                "chart": "mostPopular",
                "regionCode": region,
                "maxResults": 25,
            },
        )
        for item in payload.get("items", []):
            video_id = item.get("id")
            if not video_id:
                continue
            ids.add(str(video_id))
            _add_region(region_presence, str(video_id), region)

    queries = settings.search_queries
    if queries:
        start = int(state.get("query_cursor", 0)) % len(queries)
        take = min(settings.max_searches_per_run, len(queries))
        selected = [queries[(start + i) % len(queries)] for i in range(take)]
        state["query_cursor"] = (start + take) % len(queries)
        published_after = (now - timedelta(days=7)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        for query in selected:
            payload = _get(
                settings,
                "search",
                {
                    "part": "snippet",
                    "type": "video",
                    "order": "date",
                    "q": query,
                    "maxResults": 10,
                    "publishedAfter": published_after,
                    "regionCode": settings.regions[0] if settings.regions else "US",
                    "relevanceLanguage": "en",
                    "safeSearch": "moderate",
                },
            )
            for item in payload.get("items", []):
                video_id = (item.get("id") or {}).get("videoId")
                if video_id:
                    ids.add(str(video_id))
                    _add_region(region_presence, str(video_id), settings.regions[0] if settings.regions else "US")

    if not ids:
        return []

    detail_by_id: dict[str, dict[str, Any]] = {}
    id_list = list(ids)
    # videos.list accepts up to 50 comma-separated IDs per request.
    for offset in range(0, len(id_list), 50):
        payload = _get(
            settings,
            "videos",
            {
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(id_list[offset : offset + 50]),
                "maxResults": 50,
            },
        )
        for item in payload.get("items", []):
            detail_by_id[str(item["id"])] = item

    scored: list[dict[str, Any]] = []
    history = state.setdefault("videos", {})
    for video_id, item in detail_by_id.items():
        item["regions"] = sorted(region_presence.get(video_id, set()))
        scored_item = score_video(item, history.get(video_id), now)
        scored.append(scored_item)

    scored.sort(
        key=lambda item: (
            float(item.get("trend", {}).get("score", 0)),
            float(item.get("statistics", {}).get("viewCount", 0) or 0),
        ),
        reverse=True,
    )
    scored = scored[: settings.max_candidates]

    # Store the new snapshot only after calculating velocity against the previous snapshot.
    for item in scored:
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        history[str(item["id"])] = {
            "view_count": int(stats.get("viewCount", 0) or 0),
            "last_seen": utc_now_iso(),
            "title": snippet.get("title", "")[:200],
            "channel_title": snippet.get("channelTitle", "")[:120],
            "published_at": snippet.get("publishedAt"),
            "trend_score": item.get("trend", {}).get("score"),
            "regions": item.get("regions", []),
        }
    return scored


def public_video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def candidate_summary(video: dict[str, Any]) -> dict[str, Any]:
    snippet = video.get("snippet", {})
    stats = video.get("statistics", {})
    trend = video.get("trend", {})
    return {
        "video_id": str(video.get("id", "")),
        "title": str(snippet.get("title", "")),
        "creator": str(snippet.get("channelTitle", "")),
        "url": public_video_url(str(video.get("id", ""))),
        "published_at": snippet.get("publishedAt"),
        "views": int(stats.get("viewCount", 0) or 0),
        "likes": int(stats.get("likeCount", 0) or 0),
        "comments": int(stats.get("commentCount", 0) or 0),
        "description": str(snippet.get("description", ""))[:1200],
        "regions": video.get("regions", []),
        "trend_score": float(trend.get("score", 0)),
        "commercial_fit_proxy": float(trend.get("commercial_fit_proxy", 0)),
        "commercial_fit_note": "heuristic from public title/category only; not actual revenue or RPM",
        "views_per_hour_estimate": float(trend.get("views_per_hour_estimate", 0)),
        "age_hours": float(trend.get("age_hours", 0)),
        "category_id": str(snippet.get("categoryId", "")),
    }
