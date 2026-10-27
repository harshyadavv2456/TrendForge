"""TrendForge scheduled pipeline entrypoint."""
from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

from .config import Settings
from .publisher import upload_short
from .renderer import render_short
from .report import render_report, write_summary
from .scoring import parse_time
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
    return sum(
        1 for item in state.get("published", [])
        if str(item.get("published_at", item.get("created_at", ""))).startswith(today)
    )


def _recently_used(
    state: dict[str, Any],
    video_id: str,
    fingerprint: str | None = None,
    history_days: int = 21,
) -> bool:
    now = datetime.now(timezone.utc)
    for item in state.get("generated", []):
        stamp = item.get("created_at", "")
        try:
            when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        elapsed = (now - when).total_seconds()
        if 0 <= elapsed <= 7 * 86400 and item.get("source_video_id") == video_id:
            return True
        if fingerprint and 0 <= elapsed <= history_days * 86400 and item.get("content_hash") == fingerprint:
            return True
    return False


def _is_fresh(candidate: dict[str, Any], max_age_days: int) -> bool:
    published = candidate.get("snippet", {}).get("publishedAt")
    if not published:
        return False
    age_seconds = (datetime.now(timezone.utc) - parse_time(str(published))).total_seconds()
    # A small clock skew is harmless; missing dates and significantly future-dated
    # items are rejected rather than silently treated as fresh.
    return -3600 <= age_seconds <= max_age_days * 86400


def _self_test() -> int:
    now = datetime.now(timezone.utc)
    video = {
        "id": "self-test",
        "snippet": {
            "title": "A creator challenge tests an unusual idea",
            "channelTitle": "Example Creator",
            "publishedAt": now.isoformat(),
            "categoryId": "24",
        },
        "discovery": {"source_kind": "creator_latest", "source_label": "Latest uploads from Example Creator", "source_rank": 1},
    }
    summary = candidate_summary(video)
    assert summary["video_id"] == "self-test"
    assert summary["discovery"]["source_kind"] == "creator_latest"
    assert "views" not in summary
    assert _is_fresh(video, 14)
    assert not _is_fresh({"snippet": {}}, 14)
    print("TrendForge self-test passed: discovery provenance, raw API metadata normalization and freshness checks.")
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
    return_code = 0
    state["last_run"] = utc_now_iso()
    state["last_error"] = None

    try:
        settings.validate_for_run()
        LOG.info("Fetching YouTube native popular charts in %s and latest creator uploads", ",".join(settings.regions))
        candidates = fetch_candidates(settings, state)
        # Keep the ordering supplied by YouTube's own popular chart and search endpoints.
        # Only use the published timestamp to avoid discussing stale candidates.
        trim_history(state, settings.history_retention_days)
        eligible = [
            item for item in candidates
            if _is_fresh(item, settings.max_source_age_days)
        ]

        if not eligible:
            status = "NO PUBLISH"
            report_message = (
                f"No discovered candidate was published within the last {settings.max_source_age_days} days. "
                "Nothing was generated or published."
            )
            LOG.info(report_message)
        elif settings.auto_publish and _published_today(state) >= settings.max_uploads_per_day:
            status = "DAILY CAP"
            report_message = (
                f"The daily publishing cap ({settings.max_uploads_per_day}) has been reached. "
                "Discovery completed, but no additional Short was generated or uploaded."
            )
            LOG.info(report_message)
        else:
            chosen = None
            script = None
            # A small number of attempts limits model spend while allowing a failed angle
            # or duplicate script to fall through to another native-ordered candidate.
            for candidate in eligible[:4]:
                source_id = str(candidate.get("id", ""))
                if _recently_used(state, source_id, history_days=settings.history_retention_days):
                    errors.append("Skipped a candidate: its source was used in the previous 7 days.")
                    continue
                try:
                    candidate_script = generate_script(settings, candidate)
                    fingerprint = _content_hash(candidate_script["narration"])
                    if _recently_used(
                        state, source_id, fingerprint, history_days=settings.history_retention_days
                    ):
                        errors.append("Skipped a candidate: generated narration duplicates recent content.")
                        continue
                    chosen, script = candidate, candidate_script
                    break
                except ScriptGenerationError as exc:
                    errors.append(f"Script rejected by validation: {exc}")
                    LOG.warning("Candidate script rejected by validation: %s", exc)

            if chosen is None or script is None:
                status = "NO PUBLISH"
                report_message = (
                    "Discovery ran, but the candidate set was duplicate, stale or failed script validation. "
                    "Nothing was published."
                )
            else:
                discovery = chosen.get("discovery", {})
                LOG.info("Rendering original Short from the selected native-ordered candidate.")
                render_result = render_short(settings, chosen, script)
                preview = str(render_result["path"])
                LOG.info(
                    "Rendered %s (%.1fs, %s bytes)",
                    render_result["path"].name,
                    render_result["duration_seconds"],
                    render_result["size_bytes"],
                )
                now_iso = utc_now_iso()
                fingerprint = _content_hash(script["narration"])
                if settings.auto_publish:
                    uploaded = upload_short(settings, render_result["path"], script, publish=True)
                    state.setdefault("published", []).append({
                        "video_id": uploaded["video_id"],
                        "url": uploaded["url"],
                        "title": uploaded["title"],
                        "source_video_id": str(chosen.get("id", "")),
                        "source_video_url": candidate_summary(chosen)["url"],
                        "published_at": now_iso,
                        "privacy_status": uploaded["privacy_status"],
                        "content_hash": fingerprint,
                    })
                    state.setdefault("generated", []).append({
                        "source_video_id": str(chosen.get("id", "")),
                        "content_hash": fingerprint,
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
                    state.setdefault("generated", []).append({
                        "source_video_id": str(chosen.get("id", "")),
                        "content_hash": fingerprint,
                        "title": script["title"],
                        "created_at": now_iso,
                        "preview_only": True,
                    })
                    status = "PREVIEW ONLY"
                    report_message = (
                        "The Short was rendered successfully, but AUTO_PUBLISH is false. "
                        "Turn it on only after validating the preview, channel authorization and privacy setting."
                    )
    except Exception as exc:
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
        except Exception as exc:
            LOG.exception("Could not persist TrendForge state")
            status = "FAILED"
            report_message = f"Could not persist the run state: {type(exc).__name__}: {str(exc)[:300]}"
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
