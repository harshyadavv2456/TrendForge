import json

from trendforge.scriptwriter import _extract_json


def test_json_extraction_from_plain_response() -> None:
    data = _extract_json(json.dumps({"title": "A title", "quality_score": 80}))
    assert data["quality_score"] == 80


def test_json_extraction_from_markdown_fence() -> None:
    data = _extract_json('\\x60\\x60\\x60json\n{"angle":"A useful insight"}\n\\x60\\x60\\x60')
    assert data["angle"] == "A useful insight"
