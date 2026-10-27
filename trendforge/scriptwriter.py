"""Generate original, fact-constrained Shorts scripts from public metadata, never copied footage."""
from __future__ import annotations

import json
import re
from typing import Any
import requests

from .config import Settings
from .youtube import candidate_summary


class ScriptGenerationError(RuntimeError):
    pass


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^\x60{3}(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\x60{3}$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise ScriptGenerationError("Language model did not return a JSON object.")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ScriptGenerationError("Language model returned malformed JSON.") from exc
    if not isinstance(data, dict):
        raise ScriptGenerationError("Language model response must be a JSON object.")
    return data


def _word_count(value: str) -> int:
    return len(re.findall(r"\b[\w’'-]+\b", value))


def generate_script(settings: Settings, candidate: dict[str, Any]) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise ScriptGenerationError("OPENAI_API_KEY is required to generate original scripts.")
    source = candidate_summary(candidate)
    prompt = {
        "source_observations": source,
        "objective": (
            "Create one original, useful, American-English YouTube Short about a creator-economy trend. "
            "Use the source video only as a public trend signal, not as footage to reproduce. "
            "Make a clearly original analysis/lesson about audience attention, storytelling, production strategy, "
            "or the business of creators. Never imitate the creator's voice or claim to quote them."
        ),
        "strict_rules": [
            "Use only the provided facts for claims about the creator, title, views, likes, comments, date and source video.",
            "Do not invent creator earnings, subscribers, motives, statements, private information, or unseen scenes.",
            "If you propose why a format may attract attention, label it as analysis or a hypothesis, not a verified fact.",
            "Do not present the source video's title as proof of what happened inside the video.",
            "No fake urgency, fabricated records, financial promises, misleading titles or keyword stuffing.",
            "The video must provide a distinct insight, not a generic summary or interchangeable template.",
            "Total spoken narration must be 95–135 words, divided into 4 scenes with 20–40 spoken words each.",
            "All on-screen headlines must be short and readable on a phone, ideally 3–7 words.",
            "Use a natural editorial tone, clear American English and a strong but honest opening hook.",
            "No copyrighted lyrics, copied scripts, copied transcript, imitation voice, or unlicensed footage.",
            "Generate 3–5 relevant hashtags and 5–10 relevant tags. Include #Shorts, and use #MrBeast or another creator hashtag only if directly relevant.",
            "The description must link to the source metadata/video and explain that the Short is original commentary based on public metadata.",
        ],
        "required_json_shape": {
            "title": "string, <= 90 characters, accurate and compelling",
            "angle": "one sentence explaining the distinct original insight",
            "quality_score": "integer 0-100, conservative self-assessment",
            "narration_disclosure": "one sentence noting AI-assisted narration/graphics",
            "scenes": [
                {
                    "headline": "short on-screen line",
                    "narration": "spoken words for this scene, 20-40 words",
                    "visual": "original graphic concept, not footage instructions",
                }
            ],
            "tags": ["string"],
            "hashtags": ["#Shorts", "#Relevant"],
            "description": "string; include source link and concise context",
        },
    }
    payload = {
        "model": settings.openai_model,
        "temperature": 0.8,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an original short-form editorial producer. Create accurate, useful commentary, "
                    "not recycled viral clips. Return valid JSON only. Keep the storytelling specific to the "
                    "provided source observations and offer a genuine takeaway."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
    }
    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=90,
        )
    except requests.RequestException as exc:
        raise ScriptGenerationError(f"OpenAI script API network error: {exc}") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message", response.text[:300])
        except ValueError:
            detail = response.text[:300]
        raise ScriptGenerationError(f"OpenAI script API returned HTTP {response.status_code}: {detail}")
    try:
        raw = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ScriptGenerationError("Unexpected OpenAI chat completion response.") from exc
    result = _extract_json(raw)

    scenes = result.get("scenes")
    if not isinstance(scenes, list) or not 4 <= len(scenes) <= 5:
        raise ScriptGenerationError("Generated script must contain 4–5 scenes.")
    normalized_scenes = []
    for scene in scenes:
        if not isinstance(scene, dict):
            raise ScriptGenerationError("Scene entries must be objects.")
        headline = re.sub(r"\s+", " ", str(scene.get("headline", ""))).strip()[:56]
        spoken = re.sub(r"\s+", " ", str(scene.get("narration", ""))).strip()
        visual = re.sub(r"\s+", " ", str(scene.get("visual", ""))).strip()[:180]
        if not headline or not spoken or not visual:
            raise ScriptGenerationError("Every scene needs a headline, narration and original visual concept.")
        normalized_scenes.append({"headline": headline, "narration": spoken, "visual": visual})
    narration = " ".join(scene["narration"] for scene in normalized_scenes)
    words = _word_count(narration)
    if not 95 <= words <= 155:
        raise ScriptGenerationError(f"Generated narration has {words} words; required range is 95–155.")
    try:
        quality_score = int(result.get("quality_score", 0))
    except (ValueError, TypeError):
        quality_score = 0
    if quality_score < settings.min_script_quality:
        raise ScriptGenerationError(f"Script quality self-score {quality_score} is below threshold {settings.min_script_quality}.")
    angle = re.sub(r"\s+", " ", str(result.get("angle", ""))).strip()
    if len(angle) < 35:
        raise ScriptGenerationError("Script lacks a specific original editorial angle.")
    title = re.sub(r"\s+", " ", str(result.get("title", ""))).strip()[:90]
    if len(title) < 12:
        raise ScriptGenerationError("Generated title is missing or too short.")
    tags = []
    for tag in result.get("tags", []):
        tag = re.sub(r"[^\w\s-]", "", str(tag)).strip()
        if tag and tag.lower() not in {t.lower() for t in tags}:
            tags.append(tag[:45])
    tags = tags[:10]
    hashtags = []
    for tag in result.get("hashtags", []):
        tag = str(tag).strip()
        if not re.fullmatch(r"#[A-Za-z0-9_]{2,30}", tag):
            continue
        if tag.lower() not in {t.lower() for t in hashtags}:
            hashtags.append(tag)
    if "#shorts" not in {tag.lower() for tag in hashtags}:
        hashtags.insert(0, "#Shorts")
    hashtags = hashtags[:5]
    disclosure = re.sub(r"\s+", " ", str(result.get("narration_disclosure", ""))).strip()
    description = str(result.get("description", "")).strip()
    source_url = source["url"]
    if source_url not in description:
        description = f"{description}\n\nSource video and public metadata: {source_url}"
    description += "\n\nOriginal commentary and custom motion graphics. AI-assisted narration/production. #Shorts " + " ".join(hashtags[:4])
    description = description[:4800]
    return {
        "title": title,
        "angle": angle,
        "quality_score": quality_score,
        "narration_disclosure": disclosure,
        "narration": narration,
        "scenes": normalized_scenes,
        "tags": tags,
        "hashtags": hashtags,
        "description": description,
        "source": source,
        "word_count": words,
    }
