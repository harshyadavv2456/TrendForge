"""Configuration loading and validation."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _pipe_list(name: str, default: str) -> list[str]:
    return [part.strip() for part in os.getenv(name, default).split("|") if part.strip()]


@dataclass(frozen=True)
class Settings:
    youtube_api_key: str
    openai_api_key: str
    youtube_client_id: str
    youtube_client_secret: str
    youtube_refresh_token: str
    auto_publish: bool
    max_uploads_per_day: int
    max_source_age_days: int
    max_candidates: int
    max_searches_per_run: int
    max_creator_channels_per_run: int
    history_retention_days: int
    min_script_quality: int
    regions: list[str]
    search_queries: list[str]
    creator_handles: list[str]
    openai_model: str
    tts_model: str
    tts_voice: str
    tts_instructions: str
    video_language: str
    video_category_id: str
    video_privacy_status: str
    root: Path

    @classmethod
    def from_env(cls) -> "Settings":
        root = Path(__file__).resolve().parents[1]
        regions = [r.upper() for r in _pipe_list("YOUTUBE_REGIONS", "US|GB|CA|AU")]
        regions = [r for r in regions if len(r) == 2]
        if not regions:
            raise ValueError("YOUTUBE_REGIONS must contain at least one two-letter region code")
        queries = _pipe_list(
            "YOUTUBE_SEARCH_QUERIES",
            "creator economy|YouTube challenge|AI creators|gaming creator|business creator|creator strategy|viral storytelling|technology creator",
        )
        handles = [h.lstrip("@").strip() for h in _pipe_list(
            "YOUTUBE_CREATOR_HANDLES",
            "MrBeast|MarkRober|RyanTrahan|Sidemen|Airrack|Mrwhosetheboss|MKBHD",
        ) if h.lstrip("@").strip()]
        return cls(
            youtube_api_key=os.getenv("YOUTUBE_API_KEY", "").strip(),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            youtube_client_id=os.getenv("YOUTUBE_CLIENT_ID", "").strip(),
            youtube_client_secret=os.getenv("YOUTUBE_CLIENT_SECRET", "").strip(),
            youtube_refresh_token=os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip(),
            auto_publish=_bool("AUTO_PUBLISH", False),
            max_uploads_per_day=_int("MAX_UPLOADS_PER_DAY", 2, 0, 10),
            max_source_age_days=_int("MAX_SOURCE_AGE_DAYS", 14, 1, 30),
            max_candidates=_int("MAX_CANDIDATES", 35, 5, 100),
            max_searches_per_run=_int("MAX_SEARCHES_PER_RUN", 4, 1, 10),
            max_creator_channels_per_run=_int("MAX_CREATOR_CHANNELS_PER_RUN", 4, 1, 10),
            history_retention_days=_int("HISTORY_RETENTION_DAYS", 21, 7, 30),
            min_script_quality=_int("MIN_SCRIPT_QUALITY", 70, 50, 100),
            regions=regions,
            search_queries=queries,
            creator_handles=handles,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip(),
            tts_model=os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts").strip(),
            tts_voice=os.getenv("OPENAI_TTS_VOICE", "coral").strip(),
            tts_instructions=os.getenv(
                "OPENAI_TTS_INSTRUCTIONS",
                "Speak with clear, energetic, natural American-English delivery. Sound curious and analytical, not exaggerated or clickbait-heavy.",
            ).strip(),
            video_language=os.getenv("VIDEO_LANGUAGE", "en").strip(),
            video_category_id=os.getenv("VIDEO_CATEGORY_ID", "24").strip(),
            video_privacy_status=os.getenv("VIDEO_PRIVACY_STATUS", "public").strip().lower(),
            root=root,
        )

    def validate_for_run(self) -> None:
        missing = []
        if not self.youtube_api_key:
            missing.append("YOUTUBE_API_KEY")
        if not self.openai_api_key:
            missing.append("OPENAI_API_KEY")
        if self.auto_publish:
            for name, value in (
                ("YOUTUBE_CLIENT_ID", self.youtube_client_id),
                ("YOUTUBE_CLIENT_SECRET", self.youtube_client_secret),
                ("YOUTUBE_REFRESH_TOKEN", self.youtube_refresh_token),
            ):
                if not value:
                    missing.append(name)
        if missing:
            raise RuntimeError(
                "Missing required configuration: " + ", ".join(missing)
                + ". Add these as GitHub Actions secrets (or local environment variables). "
                + "See docs/SETUP.md."
            )
        if self.video_privacy_status not in {"public", "unlisted", "private"}:
            raise ValueError("VIDEO_PRIVACY_STATUS must be public, unlisted, or private")
        if self.auto_publish and self.max_uploads_per_day == 0:
            raise ValueError("AUTO_PUBLISH is true but MAX_UPLOADS_PER_DAY is 0")
