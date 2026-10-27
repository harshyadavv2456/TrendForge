import json
from datetime import datetime, timedelta, timezone

from trendforge.state import blank_state, load_state, save_state, trim_history


def test_state_round_trip(tmp_path) -> None:
    path = tmp_path / "state.json"
    state = blank_state()
    state["query_cursor"] = 3
    save_state(path, state)
    loaded = load_state(path)
    assert loaded["query_cursor"] == 3
    assert loaded["published"] == []


def test_trim_removes_old_history() -> None:
    state = blank_state()
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    recent = datetime.now(timezone.utc).isoformat()
    state["generated"] = [
        {"source_video_id": "old", "created_at": old},
        {"source_video_id": "new", "created_at": recent},
    ]
    trim_history(state, retention_days=45)
    assert len(state["generated"]) == 1
    assert state["generated"][0]["source_video_id"] == "new"
