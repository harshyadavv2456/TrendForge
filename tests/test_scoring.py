from datetime import datetime, timezone

from trendforge.scoring import annotate_discovery
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
    }


def test_discovery_provenance_preserves_native_order() -> None:
    now = datetime(2026, 10, 27, tzinfo=timezone.utc)
    video = annotate_discovery(
        sample_video(now.isoformat()),
        source_kind="popular_chart",
        source_label="YouTube mostPopular chart · US",
        source_rank=2,
        region="US",
    )
    assert video["discovery"]["source_kind"] == "popular_chart"
    assert video["discovery"]["source_rank"] == 2
    assert video["discovery"]["region"] == "US"


def test_candidate_summary_uses_raw_api_values_without_custom_metrics() -> None:
    now = datetime.now(timezone.utc)
    video = annotate_discovery(
        sample_video(now.isoformat()),
        source_kind="creator_latest",
        source_label="Latest uploads from Example Creator (@ExampleCreator)",
        source_rank=1,
    )
    summary = candidate_summary(video)
    assert summary["url"] == "https://www.youtube.com/watch?v=abc123"
    assert summary["creator"] == "Example Creator"
    assert summary["views"] == 1_200_000
    assert summary["discovery"]["source_kind"] == "creator_latest"
    assert "trend_score" not in summary
