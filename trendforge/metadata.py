"""Title/description/hashtag builder for Shorts parts (no AI calls)."""
from __future__ import annotations

import re
from typing import Any

TITLE_MAX = 59
HOOKS = [
    "Wait for it",
    "Nobody saw this coming",
    "This moment is unreal",
    "Watch till the end",
    "The best part",
    "You won't believe this",
]


def _hashtag(text: str) -> str:
    word = re.sub(r"[^A-Za-z0-9]", "", text or "")
    return f"#{word[:30]}" if len(word) >= 2 else ""


def _trim_words(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.:;-|")
    return cut or text[:limit]


def build_title(source_title: str, part: int, total: int) -> str:
    hook = HOOKS[(part - 1) % len(HOOKS)]
    suffix = f" (Part {part})" if total > 1 else ""
    room = TITLE_MAX - len(hook) - len(suffix) - 2
    core = _trim_words(re.sub(r"[#|]", " ", source_title or ""), max(room, 0))
    title = f"{hook}: {core}{suffix}" if core else f"{hook}{suffix}"
    return title[:TITLE_MAX].strip()


def hashtags(creator: str, source_title: str) -> list[str]:
    tags = ["#Shorts"]
    creator_tag = _hashtag(creator)
    if creator_tag:
        tags.append(creator_tag)
    words = [w for w in re.findall(r"[A-Za-z]{4,}", source_title or "") if w.lower() not in {"this", "with", "that", "from", "what", "have", "your"}]
    if words:
        tags.append(_hashtag(words[0].capitalize()))
    tags.append("#Highlights")
    seen, out = set(), []
    for t in tags:
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:4]


def build_script(source: dict[str, Any], part: int, total: int) -> dict[str, Any]:
    title = str(source.get("title") or "Highlight")
    creator = str(source.get("creator") or "the original creator")
    url = str(source.get("url") or "")
    tags = hashtags(creator, title)
    lines = [
        f"Part {part} of {total} from \"{title}\" by {creator}.",
        "",
        f"All credit to {creator}. Watch the full original video: {url}" if url else f"All credit to {creator}.",
        "",
        "Follow for the next part.",
        "",
        " ".join(tags),
    ]
    return {
        "title": build_title(title, part, total),
        "description": "\n".join(lines)[:4800],
        "tags": [t.lstrip("#") for t in tags] + ["clip"],
        "source": {"url": url, "creator": creator, "title": title},
    }
