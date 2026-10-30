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
    assert settings.tts_voice == "en_US-lessac-medium"


def test_groq_key_is_optional(monkeypatch) -> None:
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-youtube-key")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("AUTO_PUBLISH", "false")
    Settings.from_env().validate_for_run()  # template script is used instead


def test_template_script_without_groq(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "")
    from trendforge.scriptwriter import generate_script
    cand = {"id": "x1", "snippet": {"title": "A Very Long Trending Video Title That Goes On And On Forever", "channelTitle": "Airrack"},
            "statistics": {"viewCount": "1234567"}}
    s = generate_script(Settings.from_env(), cand)
    assert len(s["title"]) < 60 and "#Shorts" in s["description"] and "watch?v=x1" in s["description"]
    assert 4 <= len(s["scenes"]) <= 5 and s["word_count"] < 140


def test_handles_strip_at_prefix(monkeypatch) -> None:
    monkeypatch.setenv("YOUTUBE_REGIONS", "US|GB")
    monkeypatch.setenv("YOUTUBE_CREATOR_HANDLES", "@MrBeast|@MKBHD")
    monkeypatch.setenv("YOUTUBE_SEARCH_QUERIES", "AI creators")
    settings = Settings.from_env()
    assert settings.creator_handles == ["MrBeast", "MKBHD"]
