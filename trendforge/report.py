"""Markdown reporting for automated runs."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def render_report(
    candidates: list[dict[str, Any]],
    status: str,
    message: str,
    uploaded: dict[str, Any] | None = None,
    preview_path: str | None = None,
    errors: list[str] | None = None,
) -> str:
    lines = [
        "# TrendForge run report",
        "",
        f"**Status:** {status}",
        "",
        message,
        "",
        "## Highest-ranked opportunities",
        "",
        "| Score | Creator | Video | Estimated views/hour | Regions |",
        "|---:|---|---|---:|---|",
    ]
    for item in candidates[:12]:
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        trend = item.get("trend", {})
        title = str(snippet.get("title", "Untitled")).replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")
        creator = str(snippet.get("channelTitle", "Unknown")).replace("|", "\\|")
        video_id = str(item.get("id", ""))
        url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
        lines.append(
            f"| {float(trend.get('score', 0)):.1f} | {creator} | [{title}]({url}) | "
            f"{float(trend.get('views_per_hour_estimate', 0)):,.0f} | {', '.join(item.get('regions', []))} |"
        )
    if not candidates:
        lines.append("| — | — | No candidates returned | — | — |")
    if uploaded:
        lines.extend([
            "",
            "## Upload",
            "",
            f"- **Video:** [{uploaded.get('title', 'Open YouTube video')}]({uploaded.get('url', '')})",
            f"- **Privacy returned by API:** {uploaded.get('privacy_status', 'unknown')}",
            f"- **Bytes uploaded:** {int(uploaded.get('uploaded_bytes', 0)):,}",
            f"- **Result:** {uploaded.get('message', 'Uploaded')}",
        ])
    elif preview_path:
        lines.extend(["", "## Preview", "", f"Rendered video file: {Path(preview_path).name} (available in the workflow artifact)."])
    if errors:
        lines.extend(["", "## Skipped or failed candidates", ""])
        lines.extend([f"- {str(error)[:300]}" for error in errors[:8]])
    lines.extend([
        "",
        "---",
        "Trend scores are heuristics based on public metadata, not forecasts of views or revenue. Source footage is not downloaded or reused.",
    ])
    return "\n".join(lines) + "\n"


def write_summary(report: str, root: Path) -> None:
    outdir = root / "outputs"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "run-summary.md").write_text(report, encoding="utf-8")
    github_summary = __import__("os").getenv("GITHUB_STEP_SUMMARY")
    if github_summary:
        with open(github_summary, "a", encoding="utf-8") as handle:
            handle.write(report + "\n")
