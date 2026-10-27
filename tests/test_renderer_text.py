from PIL import Image, ImageDraw

from trendforge.renderer import _font, _wrap


def test_wrap_splits_long_headlines() -> None:
    image = Image.new("RGB", (400, 300))
    draw = ImageDraw.Draw(image)
    lines = _wrap(draw, "An unusually long creator economy headline for a vertical Short", _font(42, True), 300)
    assert len(lines) > 1
    assert all(line for line in lines)
