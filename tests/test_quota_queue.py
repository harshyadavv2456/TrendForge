import json
from datetime import datetime
from pathlib import Path

from trendforge import publish_queue
from trendforge.metadata import build_script, build_title
from trendforge.publisher import QuotaExceededError
from trendforge.quota import PACIFIC, QuotaLedger, pacific_day


def _queue(root: Path, sid="abc123", parts=3):
    d = root / "outputs" / "queue" / sid
    d.mkdir(parents=True)
    manifest = {"source": {"title": "I Built A Giant Robot In 24 Hours", "creator": "Mark Rober", "url": "https://youtu.be/abc123"},
                "parts": [{"part": i, "total": parts, "path": f"part-{i:02d}.mp4"} for i in range(1, parts + 1)]}
    (d / "manifest.json").write_text(json.dumps(manifest))
    for i in range(1, parts + 1):
        (d / f"part-{i:02d}.mp4").write_bytes(b"x")


def test_pacific_day_boundary():
    from datetime import timezone
    assert pacific_day(datetime(2026, 10, 31, 6, 59, tzinfo=timezone.utc)) == "2026-10-30"
    assert pacific_day(datetime(2026, 10, 31, 7, 1, tzinfo=timezone.utc)) == "2026-10-31"


def test_ledger_caps(tmp_path):
    led = QuotaLedger(tmp_path / "l.json", daily_units=10000, max_uploads_per_day=5)
    for _ in range(5):
        assert led.upload_block_reason() is None
        led.record(1600, uploads=1)
    assert "MAX_UPLOADS_PER_DAY" in led.upload_block_reason()
    led.save()
    assert QuotaLedger(tmp_path / "l.json", max_uploads_per_day=5).upload_block_reason()


def test_one_upload_per_run_and_keying(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_UPLOADS_PER_DAY", "5")
    _queue(tmp_path)
    calls = []
    def up(settings, path, script, publish=True):
        calls.append(script)
        return {"video_id": "v1", "url": "u", "privacy_status": "public"}
    assert publish_queue.publish(tmp_path, uploads_per_run=1, uploader=up) == 1
    assert len(calls) == 1
    pub = json.loads((tmp_path / "data/published.json").read_text())["published"]
    assert list(pub) == ["abc123:1"]
    assert len(publish_queue.pending_parts(tmp_path)) == 2
    assert "Part 1" in calls[0]["title"] and "part-01" not in calls[0]["title"]


def test_quota_error_stops_without_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_UPLOADS_PER_DAY", "5")
    _queue(tmp_path)
    calls = []
    def up(*a, **k):
        calls.append(1)
        raise QuotaExceededError("quotaExceeded")
    assert publish_queue.publish(tmp_path, uploads_per_run=3, uploader=up) == 0
    assert calls == [1]
    led = QuotaLedger(tmp_path / "data/quota_ledger.json")
    assert "exhausted" in led.upload_block_reason()
    assert len(publish_queue.pending_parts(tmp_path)) == 3  # nothing wiped


def test_metadata():
    t = build_title("I Built A Giant Robot In 24 Hours That Can Do Anything At All", 2, 5)
    assert len(t) < 60 and t.endswith("(Part 2)")
    s = build_script({"title": "Robot test", "creator": "Mark Rober", "url": "https://youtu.be/x"}, 1, 5)
    assert "#Shorts" in s["description"] and "https://youtu.be/x" in s["description"] and "Mark Rober" in s["description"]
