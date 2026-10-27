from PIL import Image, ImageDraw

from trendforge.renderer import _font, _wrap


def test_wrap_splits_long_headlines() -> None:
    image = Image.new("RGB", (400, 300))
    draw = ImageDraw.Draw(image)
    lines = _wrap(draw, "An unusually long creator economy headline for a vertical Short", _font(42, True), 300)
    assert len(lines) > 1
    assert all(line for line in lines)

def test_slide_render_creates_vertical_graphic(tmp_path) -> None:
    from PIL import Image
    from trendforge.renderer import _make_slide

    output = tmp_path / "slide.png"
    candidate = {
        "id": "test-video",
        "snippet": {"title": "A creator tests a new format", "channelTitle": "Example Creator"},
        "statistics": {"viewCount": "123456"},
        "trend": {"score": 72.5},
    }
    script = {"title": "An original insight"}
    scene = {
        "headline": "The format is the lesson",
        "narration": "This is a test narration.",
        "visual": "Compare the repeatable structure with one unique payoff.",
    }
    _make_slide(output, scene, 0, 4, script, candidate)
    assert output.is_file()
    with Image.open(output) as img:
        assert img.size == (1080, 1920)
        assert img.mode == "RGB"


def test_subtitle_timing_covers_all_scene_text(tmp_path) -> None:
    from trendforge.renderer import _make_subtitles

    output = tmp_path / "captions.ass"
    _make_subtitles(
        [
            {"narration": "First scene shows one idea."},
            {"narration": "Second scene develops another clear point."},
        ],
        20.0,
        output,
    )
    rendered = output.read_text(encoding="utf-8")
    assert "[V4+ Styles]" in rendered
    assert "Dialogue:" in rendered
    assert "First scene" in rendered
    assert "Second scene" in rendered
    assert "0:00:20.00" in rendered or "0:00:19." in rendered
