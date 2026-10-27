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
    assert settings.groq_model == "openai/gpt-oss-20b"
    assert settings.tts_voice == "en-us+m3"


def test_free_provider_configuration_requires_groq_and_youtube_keys(monkeypatch) -> None:
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-youtube-key")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("AUTO_PUBLISH", "false")
    settings = Settings.from_env()
    try:
        settings.validate_for_run()
    except RuntimeError as exc:
        assert "GROQ_API_KEY" in str(exc)
    else:
        raise AssertionError("Missing Groq key should fail preflight")


def test_handles_strip_at_prefix(monkeypatch) -> None:
    monkeypatch.setenv("YOUTUBE_REGIONS", "US|GB")
    monkeypatch.setenv("YOUTUBE_CREATOR_HANDLES", "@MrBeast|@MKBHD")
    monkeypatch.setenv("YOUTUBE_SEARCH_QUERIES", "AI creators")
    settings = Settings.from_env()
    assert settings.creator_handles == ["MrBeast", "MKBHD"]
