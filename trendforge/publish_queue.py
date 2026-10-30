"""Single upload path for rendered Shorts parts.

Queue layout: outputs/queue/<source_video_id>/manifest.json + part-NN.mp4.
Published parts are recorded in data/published.json keyed "<source_video_id>:<part>".
Every run uploads at most UPLOADS_PER_RUN parts, enforces MAX_UPLOADS_PER_DAY and
the Pacific-day quota ledger, and stops immediately on a quota error.

CLI:
  python -m trendforge.publish_queue status       # prints number of queued parts
  python -m trendforge.publish_queue publish      # uploads up to UPLOADS_PER_RUN
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .metadata import build_script
from .quota import UPLOAD_UNITS, QuotaLedger

LOG = logging.getLogger("trendforge.queue")


def root_dir() -> Path:
    return Path(os.getenv("TRENDFORGE_HOME") or Path(__file__).resolve().parents[1])


def queue_dir(root: Path) -> Path:
    return root / "outputs" / "queue"


def published_path(root: Path) -> Path:
    return root / "data" / "published.json"


def load_published(root: Path) -> dict[str, Any]:
    path = published_path(root)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data.get("published"), dict):
                return data
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    return {"published": {}}


def save_published(root: Path, data: dict[str, Any]) -> None:
    path = published_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def part_key(source_id: str, part: int) -> str:
    return f"{source_id}:{int(part)}"


def pending_parts(root: Path) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    published = load_published(root)["published"]
    pending = []
    qdir = queue_dir(root)
    if not qdir.exists():
        return pending
    for manifest_path in sorted(qdir.glob("*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            LOG.warning("Unreadable manifest %s; leaving it in place.", manifest_path)
            continue
        source_id = manifest_path.parent.name
        for part in sorted(manifest.get("parts", []), key=lambda p: int(p.get("part", 0))):
            path = manifest_path.parent / Path(str(part.get("path", ""))).name
            if part_key(source_id, part["part"]) in published or not path.is_file():
                continue
            pending.append((source_id, manifest, {**part, "path": str(path)}))
    return pending


def enqueue_series(root: Path, source_id: str, series_dir: Path) -> Path:
    """Move a freshly built series into the queue without touching other queued parts."""
    dest = queue_dir(root) / source_id
    dest.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((series_dir / "series-manifest.json").read_text(encoding="utf-8"))
    for part in manifest.get("parts", []):
        src = Path(part["path"])
        target = dest / src.name
        if src.resolve() != target.resolve():
            os.replace(src, target)
        part["path"] = target.name
    manifest["source"]["video_id"] = source_id
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest


def publish(root: Path, uploads_per_run: int | None = None, uploader=None, settings=None) -> int:
    """Return number of uploads made. Never loops on failure."""
    uploads_per_run = uploads_per_run if uploads_per_run is not None else int(os.getenv("UPLOADS_PER_RUN", "1"))
    ledger = QuotaLedger(root / "data" / "quota_ledger.json")
    queue = pending_parts(root)
    if not queue:
        LOG.info("Queue empty; nothing to publish.")
        return 0
    if uploader is None:
        from .config import Settings
        from .publisher import upload_short as uploader
        settings = settings or Settings.from_env()
    from .publisher import PublishError, QuotaExceededError

    data = load_published(root)
    done = 0
    for source_id, manifest, part in queue[: max(0, uploads_per_run)]:
        reason = ledger.upload_block_reason()
        if reason:
            LOG.info("Upload skipped: %s", reason)
            break
        script = build_script(manifest.get("source", {}), int(part["part"]), int(part.get("total") or len(manifest.get("parts", [])) or 1))
        try:
            result = uploader(settings, Path(part["path"]), script, publish=True)
        except QuotaExceededError as exc:
            ledger.record(UPLOAD_UNITS)
            ledger.mark_exhausted(str(exc))
            LOG.error("Quota/upload limit hit; stopping for today: %s", exc)
            break
        except PublishError as exc:
            # Charge the attempt conservatively and stop; the part stays queued for next run.
            ledger.record(UPLOAD_UNITS)
            LOG.error("Upload failed; part stays queued for the next run: %s", exc)
            break
        ledger.record(UPLOAD_UNITS, uploads=1)
        data["published"][part_key(source_id, part["part"])] = {
            "video_id": result.get("video_id"),
            "url": result.get("url"),
            "title": script["title"],
            "privacy_status": result.get("privacy_status"),
            "published_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        save_published(root, data)
        try:
            Path(part["path"]).unlink()  # free cache space; record is kept in published.json
        except OSError:
            pass
        print(f"Published {source_id} part {part['part']}: {result.get('url')} ({result.get('privacy_status')})")
        done += 1
    ledger.save()
    return done


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["status", "publish", "enqueue"])
    parser.add_argument("--source-id")
    parser.add_argument("--series-dir", type=Path)
    args = parser.parse_args()
    root = root_dir()
    if args.command == "status":
        print(len(pending_parts(root)))
        return 0
    if args.command == "enqueue":
        if not args.source_id or not args.series_dir:
            parser.error("enqueue needs --source-id and --series-dir")
        print(enqueue_series(root, args.source_id, args.series_dir))
        return 0
    publish(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
