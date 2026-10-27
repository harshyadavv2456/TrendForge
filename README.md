# TrendForge

**Autonomous, English-language creator-trend intelligence and original YouTube Shorts production — powered by GitHub Actions.**

TrendForge monitors popular charts in the US, UK, Canada and Australia, tracks selected creator channels' latest uploads, and discovers recent niche videos; it uses YouTube's native popular-chart, latest-upload and view-count search ordering; develops an original commentary angle; writes and narrates a short script; renders an original vertical video; then uploads it to your channel when configured.

> **Rights-first design:** TrendForge discovers and analyzes public metadata. It does not download or republish other creators' videos, audio, captions or thumbnails. It creates original narrated motion-graphics videos and links its research sources in the description. Do not add unlicensed source footage.

## What runs automatically

1. Fetch YouTube popular charts by region, the latest uploads from a rotating list of actual creator channels, and recent videos matching broader niche searches.
2. Preserve YouTube's own ordering, retain the source's returned position and reject stale uploads; no custom cross-channel performance or creator-revenue scores are calculated.
3. Ask the configured language model for an original, fact-constrained commentary script with a distinct insight, title, description, tags, hashtags and storyboard.
4. Generate narration locally with eSpeak NG, create original motion-graphic scene cards, add timed captions and encode a vertical MP4 with FFmpeg.
5. Run basic script validation, source/content deduplication, metadata checks and daily-volume gates.
6. Upload to the connected YouTube channel via the official resumable upload endpoint.
7. Retain only short-lived deduplication identifiers and publishing records, write a GitHub Actions summary, and retain the rendered MP4 as a short-lived workflow artifact.

The workflow runs every six hours and can also be run manually. It deliberately skips publishing when there is no suitably fresh candidate, the content fails validation, a story is a duplicate, or the daily publishing cap has been reached.

## Important limitations

- This is unattended **after one-time setup**. You must create a free Groq API key, a free YouTube API key, authorize your channel once for uploads, and add GitHub Actions secrets. GitHub Actions cannot authorize a Google account or invent API credentials on your behalf.
- GitHub Actions is a scheduled job runner, not a permanent server. Scheduled runs can be delayed and can be disabled by GitHub after 60 days without repository activity in a public repository.
- No system can guarantee views, revenue, monetization acceptance or viral results. YouTube may review the channel and its uploads under current policies.
- After the one-time secrets/OAuth setup, automated uploads are enabled by default; set AUTO_PUBLISH=false to pause posting and generate previews only. Keep the repository's default branch protected: workflows on the default branch can access configured secrets. The scheduled publisher defaults to public posting once those secrets have been configured. Never accept untrusted changes to publishing code without review.
- YouTube API quota, OAuth status and channel restrictions can limit uploads. Inspect each workflow run and YouTube Studio after initial setup.

## Setup

Read docs/SETUP.md, then configure the required GitHub repository Actions secrets:

| Secret | Purpose |
| --- | --- |
| YOUTUBE_API_KEY | Read public video metadata |
| GROQ_API_KEY | Generate original scripts with Groq free-tier models |
| YOUTUBE_CLIENT_ID | Google OAuth client ID for channel upload |
| YOUTUBE_CLIENT_SECRET | Google OAuth client secret |
| YOUTUBE_REFRESH_TOKEN | Long-lived refresh token obtained by authorizing your own channel |

Optional Actions variables are documented in docs/CONFIGURATION.md. Secrets belong in Settings → Secrets and variables → Actions, never in this repository, issue comments, logs, or source files.

## Local development

Requires Python 3.11+, FFmpeg (with libass subtitles), eSpeak NG, a Groq API key, and a YouTube API key. Create a local .env from .env.example, install dependencies, then run:

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python -m trendforge.pipeline --self-test
    python -m trendforge.pipeline

The workflow installs FFmpeg and eSpeak NG on an Ubuntu runner. Both script rendering and narration run locally; no paid TTS service is used. Never commit .env, OAuth JSON, access tokens, refresh tokens, generated media, or raw credentials.

## Project status

The repository provides the end-to-end automation and its operational guardrails. Discovery uses native YouTube chart/search ordering; it does not estimate other creators' earnings or calculate custom API-derived trend scores. Successful operation still depends on valid secrets, Google OAuth authorization, provider availability, quota, and channel eligibility. The first authenticated run should be checked in YouTube Studio to verify that upload visibility and metadata behave as intended.

A zero-API-cost sample video is generated into assets/sample/trendforge-free-demo.mp4 by GitHub Actions, with locally authored illustrative content. See assets/sample/README.md. See SECURITY.md for credential and repository-safety guidance.
