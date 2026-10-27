# TrendForge real-footage clipper

This mode cuts actual frames and audio from a source video. It does not generate replacement scenes or a recap animation.

## Run it from GitHub Actions

Open Actions → TrendForge Real-Footage Clipper → Run workflow on main. Supply:

- Source media URL: direct HTTPS URL to a video file provided by the rights holder (MP4, MOV, WebM, MKV or M4V). This must be the media file itself, not a YouTube watch URL.
- Source page URL: canonical YouTube/source page to credit.
- Source title and creator/channel.
- Rights confirmation: check only if you own the footage or have permission/a license that allows the intended edits and publication.
- Clip count and target length.
- Publish: leave unchecked to inspect/download the artifact first. Check it only after verifying rights and configuring the three YouTube OAuth secrets.

The job emits clip-01.mp4, etc., plus clip-manifest.json. Each rendered MP4 is based on a selected source time range and contains original source video/audio, vertical re-framing, timed captions when transcription succeeds, and a source-credit line. The manifest records the original start/end timestamps.

## Local run

Install FFmpeg and Python dependencies:

    pip install -r requirements-clipper.txt
    export SOURCE_RIGHTS_CONFIRMED=true
    export GROQ_API_KEY="your Groq API key"  # optional but recommended
    python -m trendforge.clipper --input "./source-video.mp4" \
      --source-url "https://www.youtube.com/watch?v=YOUR_SOURCE_ID" \
      --title "Original video title" --creator "Original channel" \
      --rights-confirmed --count 3 --seconds 30

When no Groq key is available, clipping falls back to local scene-cut heuristics. That fallback does not provide transcript captions or semantic understanding. With the Groq key, the clipper uses Groq Whisper (whisper-large-v3-turbo) for timestamped transcription and the configured Groq text model to rank candidate windows. Groq limits and availability depend on the user's account; rate-limited transcription falls back to local ranking.

To publish locally, set CLIP_AUTO_PUBLISH=true, configure YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN, and set VIDEO_PRIVACY_STATUS intentionally. The workflow defaults to artifact-only output; public publishing is opt-in.

## Critical source-video constraint

The YouTube Data API provides metadata, search results, and upload endpoints; it is not a general source-video download API. The clipper intentionally refuses YouTube watch-page and googlevideo.com download URLs rather than trying to bypass YouTube's download restrictions. For your own uploads, download the file using YouTube Studio; for another creator's upload, request the original file or an authorized downloadable copy and confirm the license/permission. A direct file URL can be hosted by the creator or their CDN.

A Creative Commons label or public availability must not be treated as proof that all embedded music, appearances, and other materials can be republished. The workflow's rights confirmation is a self-attestation, not legal verification. The clipper cannot ensure that YouTube will accept reused-content monetization. Review every clip for context, rights, accuracy, and platform policies before publishing.

## What the ranking can and cannot do

The clipper examines scene changes and, when Groq transcription works, transcript density, hook-like language, and a model ranking of self-contained moments. It selects non-overlapping windows, reframes them to 9:16, preserves source audio, creates timestamped captions, and keeps attribution visible. Automated highlight selection remains heuristic and should be reviewed before public upload. It does not claim to predict virality or guarantee that the selected moment is objectively the best.
