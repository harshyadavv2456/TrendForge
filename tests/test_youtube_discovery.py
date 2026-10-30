from datetime import datetime, timedelta, timezone

from trendforge.config import Settings
from trendforge import youtube


def test_fetch_candidates_tracks_actual_creator_channels(monkeypatch) -> None:
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    monkeypatch.setenv("YOUTUBE_REGIONS", "US")
    monkeypatch.setenv("YOUTUBE_CREATOR_HANDLES", "AlphaCreator|BetaCreator")
    monkeypatch.setenv("YOUTUBE_SEARCH_QUERIES", "creator economy")
    monkeypatch.setenv("MAX_CREATOR_CHANNELS_PER_RUN", "2")
    monkeypatch.setenv("MAX_SEARCHES_PER_RUN", "1")
    settings = Settings.from_env()
    search_channels = []
    channel_lookups = []
    now = datetime.now(timezone.utc)
    published_at = (now - timedelta(hours=3)).isoformat()

    def fake_get(settings_arg, endpoint, params):
        if endpoint == "videos" and params.get("chart") == "mostPopular":
            return {"items": []}
        if endpoint == "channels":
            channel_lookups.append(params["forHandle"])
            handle = params["forHandle"]
            return {"items": [{"id": f"UC_{handle}", "contentDetails": {"relatedPlaylists": {"uploads": f"UU_{handle}"}}}]}
        if endpoint == "playlistItems":
            search_channels.append(params["playlistId"])
            handle = params["playlistId"].removeprefix("UU_")
            return {"items": [{"contentDetails": {"videoId": f"video_{handle}", "videoPublishedAt": published_at}}]}
        if endpoint == "search":
            raise AssertionError("search.list (100 units) must not be used")
        if endpoint == "videos" and params.get("id"):
            result = []
            for video_id in params["id"].split(","):
                handle = video_id.removeprefix("video_")
                result.append({
                    "id": video_id,
                    "snippet": {
                        "title": f"{handle} creator video strategy",
                        "channelTitle": handle,
                        "publishedAt": published_at,
                        "categoryId": "24",
                        "description": "Public metadata",
                    },
                    "contentDetails": {"duration": "PT15M"},
                })
            return {"items": result}
        raise AssertionError(f"Unexpected mocked API call: {endpoint}, {params}")

    monkeypatch.setattr(youtube, "_get", fake_get)
    state = {"creator_cursor": 0, "query_cursor": 0}
    candidates = youtube.fetch_candidates(settings, state)

    assert len(candidates) == 2
    assert set(search_channels) == {"UU_AlphaCreator", "UU_BetaCreator"}
    assert state["uploads_playlists"] == {"AlphaCreator": "UU_AlphaCreator", "BetaCreator": "UU_BetaCreator"}
    # Second run uses the cached playlist IDs: no channels.list calls.
    channel_lookups.clear()
    youtube.fetch_candidates(settings, state)
    assert channel_lookups == []
    assert state["creator_cursor"] == 0
    assert all(item["discovery"]["source_kind"] == "creator_latest" for item in candidates)
    assert all("statistics" not in item for item in candidates)
    assert [item["discovery"]["source_rank"] for item in candidates] == [1, 1]
    assert "videos" not in state
    assert "creator_channels" not in state
