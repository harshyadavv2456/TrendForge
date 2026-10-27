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
        "## Current candidates (YouTube's native chart/search ordering)",
        "",
        "| Source order | Region | Creator | Video | Published (UTC) |",
        "|---|---|---|---|---|",
    ]
    for item in candidates[:12]:
        snippet = item.get("snippet", {})
        discovery = item.get("discovery", {})
        title = str(snippet.get("title", "Untitled")).replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")
        creator = str(snippet.get("channelTitle", "Unknown")).replace("|", "\\|")
        source_label = str(discovery.get("source_label", "YouTube search")).replace("|", "\\|")
        rank = int(discovery.get("source_rank", 0) or 0)
        source = f"{source_label} (position {rank})" if rank else source_label
        region = str(discovery.get("region") or "—")
        video_id = str(item.get("id", ""))
        url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
        published = str(snippet.get("publishedAt", "—"))[:19].replace("T", " ")
        lines.append(
            f"| {source} | {region} | {creator} | [{title}]({url}) | {published} |"
        )
    if not candidates:
        lines.append("| — | — | — | No candidates returned | — |")
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
        "TrendForge requests only the metadata needed for source discovery, does not cache public view counts or calculate cross-channel metrics, and never downloads or reuses source footage.",
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
