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
            return {"items": [{"id": f"id_{handle}", "snippet": {"title": handle}}]}
        if endpoint == "search" and params.get("channelId"):
            search_channels.append(params["channelId"])
            handle = params["channelId"].removeprefix("id_")
            return {"items": [{"id": {"videoId": f"video_{handle}"}}]}
        if endpoint == "search" and params.get("q"):
            assert params["order"] == "viewCount"
            return {"items": []}
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
                    "statistics": {"viewCount": "150000", "likeCount": "2400", "commentCount": "300"},
                })
            return {"items": result}
        raise AssertionError(f"Unexpected mocked API call: {endpoint}, {params}")

    monkeypatch.setattr(youtube, "_get", fake_get)
    state = {"creator_cursor": 0, "query_cursor": 0}
    candidates = youtube.fetch_candidates(settings, state)

    assert len(candidates) == 2
    assert set(search_channels) == {"id_AlphaCreator", "id_BetaCreator"}
    assert set(channel_lookups) == {"AlphaCreator", "BetaCreator"}
    assert state["creator_cursor"] == 0
    assert all(item["discovery"]["source_kind"] == "creator_latest" for item in candidates)
    assert [item["discovery"]["source_rank"] for item in candidates] == [1, 1]
    assert "videos" not in state
    assert "creator_channels" not in state
