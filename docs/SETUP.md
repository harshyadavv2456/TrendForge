# TrendForge: one-time setup

After setup, GitHub Actions can discover candidates, render original Shorts, and publish them on a schedule without a per-video approval step. Credentials and a one-time channel authorization are still required; GitHub cannot obtain these on your behalf.

## 1. Create the YouTube Data API key

1. Open the Google Cloud Console and create or select a dedicated project.
2. Enable **YouTube Data API v3**.
3. Create an API key and restrict it to YouTube Data API v3 where possible.
4. Add the key as repository secret YOUTUBE_API_KEY.

The key is used only to read public metadata. It cannot authorize channel uploads.

## 2. Create OAuth credentials for your own channel

1. In the same Google Cloud project, configure the OAuth consent screen and create an OAuth Client ID of type **Desktop app**.
2. Configure the consent screen as required for your Google account and add your account as a test user if the app is in Testing.
3. For long-running automation, be aware that an external OAuth app left in Testing normally issues refresh tokens that expire after seven days when using YouTube upload scopes. Move the app to the appropriate production status and complete Google's verification steps if required before relying on unattended publishing.
4. Download the Desktop app OAuth client JSON to your computer as client_secret.json. Do not add it to this public repository.
5. From a local terminal, in a local checkout of TrendForge, install requirements and run:

       python -m pip install -r requirements.txt
       python scripts/authorize_youtube.py --client-secrets /path/to/client_secret.json --output "$HOME/.trendforge/token.json"

6. A browser opens. Sign in to the Google account whose YouTube channel should publish the videos and grant the requested upload permission.
7. The helper saves the token locally with restrictive file permissions. From that local file, copy the refresh_token value into repository secret YOUTUBE_REFRESH_TOKEN. Also add the client_id as YOUTUBE_CLIENT_ID and client_secret as YOUTUBE_CLIENT_SECRET. These values must all come from the same OAuth client.
8. Delete the local token file when no longer needed, or keep it securely outside the repository.

Never paste OAuth tokens or API secrets into GitHub issues, commit messages, source files, pull requests, or this chat. Do not create a Google service account for channel uploads; YouTube Data API channel actions require user OAuth.

## 3. Add the OpenAI API key

Create an API key for an account with API access and billing/credits enabled. Add it as repository secret OPENAI_API_KEY. The pipeline uses a language model for the original script and a text-to-speech model for narration. API use can incur charges; set a spend limit or alert in your provider account.

## 4. Add the GitHub Actions secrets

Open the repository's **Settings → Secrets and variables → Actions → New repository secret** and add:

- YOUTUBE_API_KEY
- OPENAI_API_KEY
- YOUTUBE_CLIENT_ID
- YOUTUBE_CLIENT_SECRET
- YOUTUBE_REFRESH_TOKEN

The workflow passes secrets only to the main pipeline step, not to dependency installation or the unit-test step. No credential belongs in a committed file. The pipeline preflight skips all API work until YOUTUBE_API_KEY and OPENAI_API_KEY are present; if AUTO_PUBLISH is true, all three OAuth secrets must also exist.

## 5. Configure repository variables

Under **Settings → Secrets and variables → Actions → Variables**, add:

| Variable | First-run value | Production suggestion |
| --- | --- | --- |
| AUTO_PUBLISH | false | true, after validating a preview |
| MAX_UPLOADS_PER_DAY | 2 | 1–2 to start |
| MAX_SEARCHES_PER_RUN | 4 | 4 |
| YOUTUBE_REGIONS | US, GB, CA, AU | Same |
| VIDEO_PRIVACY_STATUS | private | public after verifying upload behavior |

Other supported variables are listed in CONFIGURATION.md. If an optional variable is absent, the workflow uses its default.

## 6. Enable Actions and run the first preview

1. Under **Settings → Actions → General**, ensure Actions are allowed for the repository. Workflow permissions must allow the workflow's GITHUB_TOKEN to write repository contents so it can update data/state.json. Do not grant broad organization permissions unnecessarily.
2. Keep the default branch set to main. The publishing workflow deliberately runs only from main.
3. Trigger **Actions → TrendForge Shorts Pipeline → Run workflow**.
4. Keep AUTO_PUBLISH=false for the first run. If an eligible recent candidate is available, the workflow should render a motion-graphic MP4 and attach it as a short-lived artifact. The run report is also written to the Actions summary.
5. Inspect the preview, narration, captions, factual accuracy and metadata artifact. If no fresh candidate is found or all scripts fail validation, nothing is rendered; inspect the run summary before changing the freshness window.
6. After you are satisfied and OAuth is stable, change AUTO_PUBLISH=true and VIDEO_PRIVACY_STATUS=public. The schedule will then publish up to MAX_UPLOADS_PER_DAY videos without per-video approval.

Uploads, channel policy, OAuth expiry, quota errors and returned privacy status must be checked in the first production run. Do not assume an HTTP success means that a video is public; the pipeline records the actual returned privacy status.

## 7. Schedule and state

The workflow runs every six hours (UTC) and can be manually dispatched. It persists only public metadata, trend estimates, deduplication identifiers and publishing results in data/state.json. The generated MP4 and narration are not committed to Git; the upload artifact is retained for three days.

GitHub may delay scheduled jobs during periods of heavy load and automatically disable schedules for public repositories after 60 days without repository activity. If Actions stops running, open the Actions tab and re-enable the workflow if GitHub disabled it.

## Troubleshooting

- **Missing configuration:** check Actions secrets and variables spelling; secret values are masked in logs.
- **403 quota/API error:** check that YouTube Data API v3 is enabled, API key restrictions are correct, and project quota is available.
- **invalid_grant:** repeat OAuth authorization, confirm consent-screen publishing status, and update YOUTUBE_REFRESH_TOKEN.
- **Upload returns private or unlisted:** inspect the returned API status and YouTube Studio; check channel settings, API project restrictions and privacy configuration.
- **OpenAI insufficient_quota or model error:** check account billing, model access, and the configured OPENAI_MODEL / OPENAI_TTS_MODEL.
- **FFmpeg subtitle error:** check that the runner installed FFmpeg with libass subtitle support.
- **No video generated:** inspect the short-lived run artifact and summary; the source freshness window, deduplication window, script validation or daily upload cap may have prevented a post.
