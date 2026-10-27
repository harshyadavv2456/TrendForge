from trendforge.config import Settings


def test_defaults_parse_regions_creator_handles_and_queries(monkeypatch) -> None:
    for name in (
        "YOUTUBE_REGIONS",
        "YOUTUBE_CREATOR_HANDLES",
        "YOUTUBE_SEARCH_QUERIES",
        "MAX_CREATOR_CHANNELS_PER_RUN",
        "MAX_SEARCHES_PER_RUN",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_env()
    assert settings.regions == ["US", "GB", "CA", "AU"]
    assert "MrBeast" in settings.creator_handles
    assert "MKBHD" in settings.creator_handles
    assert "creator economy" in settings.search_queries
    assert settings.max_creator_channels_per_run == 4
    assert settings.max_searches_per_run == 4


def test_handles_strip_at_prefix(monkeypatch) -> None:
    monkeypatch.setenv("YOUTUBE_REGIONS", "US|GB")
    monkeypatch.setenv("YOUTUBE_CREATOR_HANDLES", "@MrBeast|@MKBHD")
    monkeypatch.setenv("YOUTUBE_SEARCH_QUERIES", "AI creators")
    settings = Settings.from_env()
    assert settings.creator_handles == ["MrBeast", "MKBHD"]
