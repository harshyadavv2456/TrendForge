"""YouTube upload using official OAuth and resumable upload endpoints."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import requests

from .config import Settings


class PublishError(RuntimeError):
    pass


def _access_token(settings: Settings) -> str:
    try:
        response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "refresh_token": settings.youtube_refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        raise PublishError(f"Google OAuth token refresh failed due to a network error: {exc}") from exc
    if response.status_code >= 400:
        try:
            data = response.json()
            detail = data.get("error_description") or data.get("error") or response.text[:300]
        except ValueError:
            detail = response.text[:300]
        if "invalid_grant" in str(detail).lower():
            detail = f"{detail}. Re-authorize the channel and replace YOUTUBE_REFRESH_TOKEN."
        raise PublishError(f"Google OAuth token refresh returned HTTP {response.status_code}: {detail}")
    try:
        token = response.json().get("access_token")
    except ValueError as exc:
        raise PublishError("Google OAuth returned invalid JSON.") from exc
    if not token:
        raise PublishError("Google OAuth response did not include an access token.")
    return str(token)


def upload_short(
    settings: Settings,
    video_path: Path,
    script: dict[str, Any],
    publish: bool = True,
) -> dict[str, Any]:
    if not video_path.exists():
        raise PublishError(f"Rendered video does not exist: {video_path}")
    token = _access_token(settings)
    desired_privacy = settings.video_privacy_status if publish else "private"
    source = script.get("source", {})
    tags = [str(t)[:45] for t in script.get("tags", [])[:10]]
    # YouTube has a total tag character limit; trim rather than sending an invalid request.
    kept_tags = []
    used_chars = 0
    for tag in tags:
        delta = len(tag) + (1 if kept_tags else 0)
        if used_chars + delta > 450:
            break
        kept_tags.append(tag)
        used_chars += delta
    description = str(script.get("description", ""))[:4800]
    payload = {
        "snippet": {
            "title": str(script["title"])[:90],
            "description": description,
            "tags": kept_tags,
            "categoryId": settings.video_category_id,
            "defaultLanguage": settings.video_language,
        },
        "status": {
            "privacyStatus": desired_privacy,
            "selfDeclaredMadeForKids": False,
            "embeddable": True,
            # The render uses clearly non-realistic graphics, not photorealistic synthetic events.
            "containsSyntheticMedia": False,
        },
    }
    size = video_path.stat().st_size
    init_url = "https://www.googleapis.com/upload/youtube/v3/videos"
    try:
        init = requests.post(
            init_url,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(size),
                "X-Upload-Content-Type": "video/mp4",
            },
            json=payload,
            timeout=45,
        )
    except requests.RequestException as exc:
        raise PublishError(f"YouTube upload session could not be created: {exc}") from exc
    if init.status_code not in (200, 201):
        try:
            detail = init.json().get("error", {}).get("message", init.text[:500])
        except ValueError:
            detail = init.text[:500]
        if init.status_code == 403:
            detail = f"{detail}. Check channel authorization, YouTube Data API status, and upload quota."
        raise PublishError(f"YouTube upload session returned HTTP {init.status_code}: {detail}")
    location = init.headers.get("Location")
    if not location:
        raise PublishError("YouTube did not return a resumable-upload Location header.")

    try:
        with video_path.open("rb") as media:
            uploaded = requests.put(
                location,
                data=media,
                headers={"Content-Type": "video/mp4", "Content-Length": str(size)},
                timeout=(45, 600),
            )
    except requests.RequestException as exc:
        raise PublishError(f"Video upload failed during transfer: {exc}") from exc
    if uploaded.status_code not in (200, 201):
        try:
            detail = uploaded.json().get("error", {}).get("message", uploaded.text[:500])
        except ValueError:
            detail = uploaded.text[:500]
        raise PublishError(f"YouTube media upload returned HTTP {uploaded.status_code}: {detail}")
    try:
        video = uploaded.json()
    except ValueError as exc:
        raise PublishError("YouTube upload response was not valid JSON.") from exc
    video_id = video.get("id")
    if not video_id:
        raise PublishError("Upload response did not include a video ID.")
    status = video.get("status", {})
    visibility = status.get("privacyStatus", "unknown")
    return {
        "video_id": str(video_id),
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "privacy_status": visibility,
        "requested_privacy_status": desired_privacy,
        "title": video.get("snippet", {}).get("title", script.get("title", "")),
        "source_video_url": source.get("url", ""),
        "uploaded_bytes": size,
        "message": (
            "Uploaded successfully."
            if visibility == desired_privacy
            else f"Upload succeeded but returned privacy status {visibility}; verify channel/API restrictions in YouTube Studio."
        ),
    }
