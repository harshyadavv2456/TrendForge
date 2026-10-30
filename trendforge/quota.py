"""Persistent YouTube Data API quota ledger keyed by Pacific-time day.

YouTube resets the daily quota at midnight America/Los_Angeles, so the ledger
uses that calendar day. The ledger lives in data/quota_ledger.json, which the
GitHub workflow persists between runs with actions/cache.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")
UPLOAD_UNITS = 1600
DEFAULT_DAILY_UNITS = 10_000
KEEP_DAYS = 8


def pacific_day(now: datetime | None = None) -> str:
    now = now or datetime.now(PACIFIC)
    return now.astimezone(PACIFIC).date().isoformat()


class QuotaLedger:
    def __init__(self, path: Path, daily_units: int | None = None, max_uploads_per_day: int | None = None):
        self.path = Path(path)
        self.daily_units = daily_units or int(os.getenv("DAILY_QUOTA_UNITS", DEFAULT_DAILY_UNITS))
        self.max_uploads = max_uploads_per_day if max_uploads_per_day is not None else int(os.getenv("MAX_UPLOADS_PER_DAY", "5"))
        self.data: dict[str, Any] = {"days": {}}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("days"), dict):
                    self.data = loaded
            except (OSError, json.JSONDecodeError):
                pass

    def today(self, now: datetime | None = None) -> dict[str, Any]:
        day = pacific_day(now)
        return self.data["days"].setdefault(day, {"units": 0, "uploads": 0, "exhausted": False})

    def record(self, units: int, uploads: int = 0, now: datetime | None = None) -> None:
        entry = self.today(now)
        entry["units"] += int(units)
        entry["uploads"] += int(uploads)

    def mark_exhausted(self, reason: str, now: datetime | None = None) -> None:
        entry = self.today(now)
        entry["exhausted"] = True
        entry["exhausted_reason"] = reason[:200]

    def upload_block_reason(self, now: datetime | None = None) -> str | None:
        entry = self.today(now)
        if entry.get("exhausted"):
            return f"quota marked exhausted today ({entry.get('exhausted_reason', '')})"
        if entry["uploads"] >= self.max_uploads:
            return f"MAX_UPLOADS_PER_DAY={self.max_uploads} reached"
        if entry["units"] + UPLOAD_UNITS > self.daily_units:
            return f"would exceed DAILY_QUOTA_UNITS={self.daily_units} (used {entry['units']})"
        return None

    def save(self, now: datetime | None = None) -> None:
        cutoff = (now or datetime.now(PACIFIC)).astimezone(PACIFIC).date() - timedelta(days=KEEP_DAYS)
        self.data["days"] = {d: v for d, v in self.data["days"].items() if d >= cutoff.isoformat()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
