"""Small, public, commit-safe state file for GitHub Actions runs."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def blank_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "last_run": None,
        "query_cursor": 0,
        "creator_cursor": 0,
        "generated": [],
        "published": [],
        "last_error": None,
    }


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return blank_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return blank_state()
        defaults = blank_state()
        defaults.update(data)
        # Drop legacy custom-score and cached channel/video snapshots. Public YouTube API
        # data should not be kept or derived into proprietary performance metrics here.
        defaults.pop("videos", None)
        defaults.pop("creator_channels", None)
        for key in ("generated", "published"):
            if not isinstance(defaults.get(key), type(blank_state()[key])):
                defaults[key] = blank_state()[key]
        return defaults
    except (OSError, json.JSONDecodeError):
        # A malformed state file must not silently erase history.
        raise RuntimeError(f"Could not parse state file {path}; restore a valid JSON version before continuing.")


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def trim_history(state: dict[str, Any], retention_days: int = 21) -> None:
    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() - retention_days * 86400
    for key in ("generated", "published"):
        kept = []
        for entry in state.get(key, []):
            stamp = entry.get("created_at") or entry.get("published_at") or entry.get("date")
            try:
                dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
                if dt.timestamp() >= cutoff:
                    kept.append(entry)
            except (ValueError, TypeError):
                kept.append(entry)
        state[key] = kept
