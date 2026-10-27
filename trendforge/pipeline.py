"""TrendForge scheduled pipeline entrypoint."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings
from .publisher import upload_short
from .renderer import render_short
from .report import render_report, write_summary
from .scoring import score_video
from .scriptwriter import ScriptGenerationError, generate_script
from .state import load_state, save_state, trim_history, utc_now_iso
from .youtube import candidate_summary, fetch_candidates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("trendforge")


def _content_hash(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _published_today(state: dict[str, Any]) -> int:
    today = datetime.now(timezone.utc).date().isoformat()
    count = 0
    for item in state.get("published", []):
        stamp = str(item.get("published_at", item.get("created_at", "")))
        if stamp.startswith(today):
            count += 1
    return count


def _recently_used(state: dict[str, Any], video_id: str, fingerprint: str | None = None) -> bool:
    now = datetime.now(timezone.utc)
    for item in state.get("generated", []):
        stamp = item.get("created_at", "")
        try:
            when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if (now - when).total_seconds() <= 7 * 86400 and item.get("source_video_id") == video_id:
            return True
        if fingerprint and item.get("content_hash") == fingerprint and (now - when).total_seconds() <= 45 * 86400:
            return True
    return False


def _self_test() -> int:
    now = datetime.now(timezone.utc)
    video = {
        "id": "self-test",
        "snippet": {"title": "A creator challenge tests an unusual idea", "publishedAt": now.isoformat(), "categoryId": "24"},
        "statistics": {"viewCount": "250000", "likeCount": "8000", "commentCount": "500"},
        "regions": ["US"],
    }
    scored = score_video(video, now=now)
    assert 0 <= scored["trend"]["score"] <= 100
    assert scored["trend"]["views_per_hour_estimate"] >= 0
    assert candidate_summary(scored)["video_id"] == "self-test"
    print("TrendForge self-test passed: score bounds, metadata normalization and report inputs.")
    return 0


def run() -> int:
    settings = Settings.from_env()
    state_path = settings.root / "data" / "state.json"
    state = load_state(state_path)
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    uploaded: dict[str, Any] | None = None
    preview: str | None = None
    report_message = ""
    status = "STARTED"
    failure: Exception | None = None
    state["last_run"] = utc_now_iso()
    state["last_error"] = None

    try:
        settings.validate_for_run()
        LOG.info("Fetching popular charts for regions %s", ",".join(settings.regions))
        candidates = fetch_candidates(settings, state)
        candidates.sort(key=lambda v: float(v.get("trend", {}).get("score", 0)), reverse=True)
        trim_history(state, settings.history_retention_days)
        threshold = settings.min_trend_score
        eligible = [
            item for item in candidates
            if float(item.get("trend", {}).get("score", 0)) >= threshold
        ]
        if not eligible:
            status = "NO PUBLISH"
            report_message = f"No candidate met the minimum trend score ({threshold:.1f}). Discovery and metadata history were updated; nothing was published."
            LOG.info(report_message)
            return_code = 0
        elif settings.auto_publish and _published_today(state) >= settings.max_uploads_per_day:
            status = "DAILY CAP"
            report_message = (
                f"The daily publishing cap ({settings.max_uploads_per_day}) has been reached. "
                "Trend discovery ran successfully, but no additional Short was generated or uploaded."
            )
            return_code = 0
        else:
            chosen = None
            script = None
            # Try a few eligible opportunities in case the first script does not pass quality checks.
            for candidate in eligible[:3]:
                source_id = str(candidate.get("id", ""))
                if _recently_used(state, source_id):
                    errors.append(f"Skipped {source_id}: source video was used in the previous 7 days.")
                    continue
                try:
                    candidate_script = generate_script(settings, candidate)
                    fingerprint = _content_hash(candidate_script["narration"])
                    if _recently_used(state, source_id, fingerprint):
                        errors.append(f"Skipped {source_id}: generated narration duplicates recent content.")
                        continue
                    chosen, script = candidate, candidate_script
                    break
                except ScriptGenerationError as exc:
                    errors.append(f"Script rejected for {source_id}: {exc}")
                    LOG.warning("Candidate %s rejected: %s", source_id, exc)
            if chosen is None or script is None:
                status = "NO PUBLISH"
                report_message = "Discovery ran, but all eligible candidates were duplicates or failed the script-quality gate. Nothing was published."
                return_code = 0
            else:
                LOG.info("Rendering original Short for source %s, score %.1f", chosen["id"], chosen["trend"]["score"])
                render_result = render_short(settings, chosen, script)
                preview = str(render_result["path"])
                LOG.info("Rendered %s (%.1fs, %s bytes)", render_result["path"].name, render_result["duration_seconds"], render_result["size_bytes"])
                if settings.auto_publish:
                    uploaded = upload_short(settings, render_result["path"], script, publish=True)
                    now_iso = utc_now_iso()
                    state.setdefault("published", []).append({
                        "video_id": uploaded["video_id"],
                        "url": uploaded["url"],
                        "title": uploaded["title"],
                        "source_video_id": str(chosen.get("id", "")),
                        "source_video_url": candidate_summary(chosen)["url"],
                        "published_at": now_iso,
                        "privacy_status": uploaded["privacy_status"],
                        "trend_score": chosen.get("trend", {}).get("score"),
                        "content_hash": _content_hash(script["narration"]),
                    })
                    state.setdefault("generated", []).append({
                        "source_video_id": str(chosen.get("id", "")),
                        "content_hash": _content_hash(script["narration"]),
                        "title": script["title"],
                        "created_at": now_iso,
                        "published_video_id": uploaded["video_id"],
                    })
                    status = "UPLOADED"
                    report_message = (
                        f"Created an original {render_result['duration_seconds']:.0f}s Short and submitted it to YouTube. "
                        "The upload result and returned privacy status are recorded below."
                    )
                    if uploaded["privacy_status"] != uploaded["requested_privacy_status"]:
                        status = "UPLOAD CHECK"
                    LOG.info("Upload response: %s (%s)", uploaded["url"], uploaded["privacy_status"])
                else:
                    status = "PREVIEW ONLY"
                    report_message = (
                        "The Short was rendered successfully, but AUTO_PUBLISH is false. "
                        "Enable AUTO_PUBLISH only after validating the channel and OAuth configuration."
                    )
                return_code = 0
        return return_code
    except Exception as exc:
        failure = exc
        status = "FAILED"
        state["last_error"] = {"at": utc_now_iso(), "type": type(exc).__name__, "message": str(exc)[:600]}
        report_message = f"Run failed: {type(exc).__name__}: {str(exc)[:500]}"
        LOG.exception("TrendForge run failed")
        return_code = 1
    finally:
        state["last_run"] = utc_now_iso()
        trim_history(state, settings.history_retention_days)
        try:
            save_state(state_path, state)
        except Exception:
            LOG.exception("Could not persist TrendForge state")
            return_code = 1
        report = render_report(candidates, status, report_message, uploaded, preview, errors)
        try:
            write_summary(report, settings.root)
        except Exception:
            LOG.exception("Could not write run summary")
        LOG.info("Run status: %s", status)
    return return_code


def main() -> int:
    parser = argparse.ArgumentParser(description="TrendForge autonomous YouTube Shorts pipeline")
    parser.add_argument("--self-test", action="store_true", help="Run local, credential-free structural checks")
    args = parser.parse_args()
    if args.self_test:
        return _self_test()
    return run()


if __name__ == "__main__":
    sys.exit(main())
