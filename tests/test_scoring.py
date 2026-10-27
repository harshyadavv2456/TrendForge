from datetime import datetime, timedelta, timezone

from trendforge.scoring import score_video
from trendforge.youtube import candidate_summary


def sample_video(published_at: str) -> dict:
    return {
        "id": "abc123",
        "snippet": {
            "title": "A creator challenge changes the game",
            "channelTitle": "Example Creator",
            "publishedAt": published_at,
            "categoryId": "24",
            "description": "Public metadata description",
        },
        "statistics": {"viewCount": "1200000", "likeCount": "25000", "commentCount": "1300"},
        "regions": ["US", "GB"],
    }


def test_score_is_bounded_and_has_velocity() -> None:
    now = datetime(2026, 10, 27, tzinfo=timezone.utc)
    video = score_video(sample_video((now - timedelta(hours=4)).isoformat()), now=now)
    assert 0 <= video["trend"]["score"] <= 100
    assert video["trend"]["views_per_hour_estimate"] > 0
    assert video["trend"]["age_hours"] >= 3.9


def test_known_view_growth_uses_previous_snapshot() -> None:
    now = datetime(2026, 10, 27, tzinfo=timezone.utc)
    previous = {"view_count": 1000, "last_seen": (now - timedelta(hours=2)).isoformat()}
    video = score_video(sample_video((now - timedelta(days=2)).isoformat()), previous, now)
    assert video["trend"]["views_per_hour_estimate"] >= 99_000


def test_candidate_summary_links_source_and_has_score() -> None:
    now = datetime.now(timezone.utc)
    video = score_video(sample_video(now.isoformat()), now=now)
    summary = candidate_summary(video)
    assert summary["url"] == "https://www.youtube.com/watch?v=abc123"
    assert summary["creator"] == "Example Creator"
    assert isinstance(summary["trend_score"], float)
