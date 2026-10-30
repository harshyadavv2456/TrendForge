"""YouTube Data API discovery: mostPopular charts + creators' uploads playlists (no search.list)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

import requests

from .config import Settings

API = "https://www.googleapis.com/youtube/v3"
TIMEOUT = 25
LOG = logging.getLogger("trendforge.youtube")

MUSIC_CATEGORY_ID = "10"  # YouTube category ID for Music
LONG_FORM_MIN_SECONDS = int(__import__("os").getenv("MIN_SOURCE_SECONDS", "600"))  # skip Shorts/short sources


def _parse_duration_seconds(duration_str: str) -> int:
    """Parse ISO 8601 duration (PT4M16S, PT1H23M45S) into total seconds."""
    match = re.match(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_str or ""
    )
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


class YouTubeAPIError(RuntimeError):
    pass


UNIT_COST = {"search": 100}  # everything else used here costs 1 unit
UNITS_USED = 0


def _get(settings: Settings, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    global UNITS_USED
    UNITS_USED += UNIT_COST.get(endpoint, 1)
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

    # Creators: resolve @handle -> uploads playlist once (cached in state), then read
    # playlistItems (1 unit) instead of search.list (100 units).
    handles = settings.creator_handles
    playlists: dict[str, str] = state.setdefault("uploads_playlists", {})
    if handles:
        start = int(state.get("creator_cursor", 0)) % len(handles)
        take = min(settings.max_creator_channels_per_run, len(handles))
        selected_handles = [handles[(start + i) % len(handles)] for i in range(take)]
        state["creator_cursor"] = (start + take) % len(handles)
        cutoff = now - timedelta(days=14)
        for handle in selected_handles:
            playlist_id = playlists.get(handle)
            if not playlist_id:
                payload = _get(settings, "channels", {"part": "contentDetails", "forHandle": handle})
                channel = next(iter(payload.get("items", [])), None)
                if not channel or not channel.get("id"):
                    LOG.warning("Could not resolve creator handle @%s; it will be retried later.", handle)
                    continue
                playlist_id = (
                    ((channel.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
                    or "UU" + str(channel["id"])[2:]
                )
                playlists[handle] = playlist_id
            latest = _get(
                settings,
                "playlistItems",
                {"part": "contentDetails", "playlistId": playlist_id, "maxResults": 5},
            )
            items = []
            for item in latest.get("items", []):
                details = item.get("contentDetails") or {}
                stamp = details.get("videoPublishedAt")
                if stamp:
                    try:
                        if datetime.fromisoformat(str(stamp).replace("Z", "+00:00")) < cutoff:
                            continue
                    except ValueError:
                        pass
                items.append(item)
            bucket = _source_bucket(
                items,
                "creator_latest",
                f"Latest uploads from @{handle}",
                lambda item: (item.get("contentDetails") or {}).get("videoId"),
                region=settings.regions[0] if settings.regions else "US",
                max_items=5,
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
        snippet = item.get("snippet", {})
        content_details = item.get("contentDetails", {})
        category_id = str(snippet.get("categoryId", ""))
        duration = _parse_duration_seconds(content_details.get("duration", ""))

        # Skip music videos — they trigger copyright claims and aren't series material.
        if category_id == MUSIC_CATEGORY_ID:
            continue
        # Require long-form (10+ min) so the series has enough footage to slice.
        if duration < LONG_FORM_MIN_SECONDS:
            continue
        item["discovery"] = source
        item["duration_seconds"] = duration
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
