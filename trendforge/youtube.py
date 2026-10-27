"""YouTube Data API discovery using native chart and search ordering only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

import requests

from .config import Settings

API = "https://www.googleapis.com/youtube/v3"
TIMEOUT = 25
LOG = logging.getLogger("trendforge.youtube")


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


def _source_bucket(
    items: list[dict[str, Any]],
    source_kind: str,
    source_label: str,
    id_getter,
    region: str | None = None,
    max_items: int | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Preserve each official endpoint's ordering and attach source provenance."""
    bucket: list[tuple[str, dict[str, Any]]] = []
    for position, item in enumerate(items, start=1):
        video_id = id_getter(item)
        if not video_id:
            continue
        bucket.append((
            str(video_id),
            {
                "source_kind": source_kind,
                "source_label": source_label,
                "source_rank": position,
                "region": region,
            },
        ))
        if max_items is not None and len(bucket) >= max_items:
            break
    return bucket


def fetch_candidates(settings: Settings, state: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch regional popular charts, newest uploads from selected creators, and niche search results.

    Candidate selection preserves YouTube's native ordering for each endpoint. This
    function intentionally does not calculate custom trend/revenue scores or store
    public video statistics between runs.
    """
    now = datetime.now(timezone.utc)
    buckets: list[list[tuple[str, dict[str, Any]]]] = []

    # YouTube's own mostPopular ordering is the primary popular-video signal.
    for region in settings.regions:
        payload = _get(
            settings,
            "videos",
            {
                "part": "snippet,contentDetails",
                "chart": "mostPopular",
                "regionCode": region,
                "maxResults": 25,
            },
        )
        bucket = _source_bucket(
            payload.get("items", []),
            "popular_chart",
            f"YouTube mostPopular chart · {region}",
            lambda item: item.get("id"),
            region=region,
            max_items=25,
        )
        if bucket:
            buckets.append(bucket)

    # Resolve only the rotating subset of creator handles on each run. Channel IDs
    # are not cached; this keeps persisted state independent of other creators' API data.
    handles = settings.creator_handles
    if handles:
        start = int(state.get("creator_cursor", 0)) % len(handles)
        take = min(settings.max_creator_channels_per_run, len(handles))
        selected_handles = [handles[(start + i) % len(handles)] for i in range(take)]
        state["creator_cursor"] = (start + take) % len(handles)
        published_after = (now - timedelta(days=14)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        discovery_region = settings.regions[0] if settings.regions else "US"
        for handle in selected_handles:
            payload = _get(
                settings,
                "channels",
                {"part": "snippet", "forHandle": handle},
            )
            channel = next(iter(payload.get("items", [])), None)
            if not channel or not channel.get("id"):
                LOG.warning("Could not resolve configured creator handle @%s; it will be retried later.", handle)
                continue
            channel_id = str(channel["id"])
            channel_title = str((channel.get("snippet") or {}).get("title", handle))[:100]
            latest = _get(
                settings,
                "search",
                {
                    "part": "snippet",
                    "type": "video",
                    "order": "date",
                    "channelId": channel_id,
                    "maxResults": 5,
                    "publishedAfter": published_after,
                    "regionCode": discovery_region,
                    "relevanceLanguage": "en",
                    "safeSearch": "moderate",
                },
            )
            bucket = _source_bucket(
                latest.get("items", []),
                "creator_latest",
                f"Latest uploads from {channel_title} (@{handle})",
                lambda item: (item.get("id") or {}).get("videoId"),
                region=discovery_region,
                max_items=5,
            )
            if bucket:
                buckets.append(bucket)

    # Broad searches use YouTube's own view-count sorting for videos published recently.
    # The source ordering is preserved, rather than re-scoring API data with custom metrics.
    queries = settings.search_queries
    if queries:
        start = int(state.get("query_cursor", 0)) % len(queries)
        take = min(settings.max_searches_per_run, len(queries))
        selected_queries = [queries[(start + i) % len(queries)] for i in range(take)]
        state["query_cursor"] = (start + take) % len(queries)
        published_after = (now - timedelta(days=7)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        discovery_region = settings.regions[0] if settings.regions else "US"
        for query in selected_queries:
            payload = _get(
                settings,
                "search",
                {
                    "part": "snippet",
                    "type": "video",
                    "order": "viewCount",
                    "q": query,
                    "maxResults": 10,
                    "publishedAfter": published_after,
                    "regionCode": discovery_region,
                    "relevanceLanguage": "en",
                    "safeSearch": "moderate",
                },
            )
            bucket = _source_bucket(
                payload.get("items", []),
                "niche_recent_top_views",
                f"Recent top-view search · {query}",
                lambda item: (item.get("id") or {}).get("videoId"),
                region=discovery_region,
                max_items=10,
            )
            if bucket:
                buckets.append(bucket)

    # Interleave source lists by each API's returned position to avoid the regional
    # chart list consuming the entire candidate cap before creator/niche sources appear.
    ordered: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    max_rank = max((len(bucket) for bucket in buckets), default=0)
    for rank_index in range(max_rank):
        for bucket in buckets:
            if rank_index >= len(bucket):
                continue
            video_id, source = bucket[rank_index]
            if video_id in seen:
                continue
            seen.add(video_id)
            ordered.append((video_id, source))
            if len(ordered) >= settings.max_candidates:
                break
        if len(ordered) >= settings.max_candidates:
            break
    if not ordered:
        return []

    detail_by_id: dict[str, dict[str, Any]] = {}
    id_list = [video_id for video_id, _ in ordered]
    for offset in range(0, len(id_list), 50):
        payload = _get(
            settings,
            "videos",
            {
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(id_list[offset:offset + 50]),
                "maxResults": 50,
            },
        )
        for item in payload.get("items", []):
            detail_by_id[str(item["id"])] = item

    candidates: list[dict[str, Any]] = []
    for video_id, source in ordered:
        item = detail_by_id.get(video_id)
        if not item:
            continue
        item["discovery"] = source
        candidates.append(item)
    return candidates


def public_video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def candidate_summary(video: dict[str, Any]) -> dict[str, Any]:
    """Expose the original API fields and source context, not derived performance metrics."""
    snippet = video.get("snippet", {})
    return {
        "video_id": str(video.get("id", "")),
        "title": str(snippet.get("title", "")),
        "creator": str(snippet.get("channelTitle", "")),
        "url": public_video_url(str(video.get("id", ""))),
        "published_at": snippet.get("publishedAt"),
        "discovery": video.get("discovery", {}),
        "category_id": str(snippet.get("categoryId", "")),
    }
