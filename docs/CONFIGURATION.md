# Configuration reference

Non-secret settings can be supplied as GitHub Actions repository **variables** or local environment variables. API keys and OAuth credentials belong only in GitHub Actions **secrets**. TrendForge uses Groq for original script generation and Piper for local neural narration; it does not call a paid TTS endpoint.

| Name | Default | Meaning |
| --- | --- | --- |
| AUTO_PUBLISH | true in the live workflow | true uploads after validation; false produces a preview only |
| MAX_UPLOADS_PER_DAY | 2 | Hard cap based on successful uploads recorded in UTC state |
| MAX_CANDIDATES | 35 | Maximum current-run candidates considered, interleaved across discovery sources |
| MAX_SEARCHES_PER_RUN | 4 | Rotating niche searches per execution; helps control YouTube API quota use |
| MAX_CREATOR_CHANNELS_PER_RUN | 4 | Number of tracked creator channels checked for latest uploads per execution |
| HISTORY_RETENTION_DAYS | 21 | Retention for deduplication/source identifiers and publishing records; maximum 30 days |
| MIN_SCRIPT_QUALITY | 70 | Minimum language-model self-score; a heuristic, not a guarantee |
| MAX_SOURCE_AGE_DAYS | 14 | Reject sources older than this window (1–30 days) |
| YOUTUBE_REGIONS | US|GB|CA|AU | Regions used for YouTube's mostPopular chart; pipe-separated codes |
| YOUTUBE_CREATOR_HANDLES | MrBeast|MarkRober|RyanTrahan|Sidemen|Airrack|Mrwhosetheboss|MKBHD | Creator channel handles, without @; pipe-separated |
| YOUTUBE_SEARCH_QUERIES | creator economy|YouTube challenge|AI creators|gaming creator|business creator|creator strategy|viral storytelling|technology creator | Rotating niche search terms; pipe-separated |
| GROQ_MODEL | openai/gpt-oss-20b | Groq script model; use one available on your Free Plan |
| LOCAL_TTS_VOICE | en_US-lessac-medium | Piper neural voice model; locally downloaded and cached, no TTS API is called |
| VIDEO_CATEGORY_ID | 24 | YouTube video category (24 = Entertainment) |
| VIDEO_PRIVACY_STATUS | public | Requested upload privacy; choose private/unlisted if desired |
| VIDEO_LANGUAGE | en | Default language metadata |

## Search strategy

TrendForge uses YouTube's native mostPopular chart order for each configured region, newest uploads from a rotating set of creator channel handles, and recent niche search results ordered by YouTube's viewCount field. Four creator channels and four niche searches run by default at each six-hour interval. This is a quota-aware sample, not an exhaustive crawl of YouTube.

## Ordering and freshness

TrendForge does not calculate a custom cross-channel trend score, view-velocity metric, commercial-fit score, or creator-revenue estimate from YouTube API data. It preserves the API's native order, interleaves source lists, and applies a published-date freshness check. It requests only the metadata needed for discovery; it does not cache public view-count snapshots or put counts in generated videos.

## Free-tier cost controls

- Groq is used for text generation only. Keep the account on the Free Plan; when free limits are reached, the API returns a rate-limit response instead of switching TrendForge to a paid model.
- Piper neural TTS runs locally with the MIT-licensed `en_US-lessac-medium` voice model. The model downloads to `~/.cache/piper` and is cached by GitHub Actions; it is not committed to Git.
- FFmpeg, Pillow, Python, and standard GitHub-hosted runners for this public repository are used for rendering. GitHub documents standard runner use in public repositories as free.
- YouTube Data API access is quota-limited. If the API quota or Groq free-tier limit is reached, the pipeline can skip/fail until the limit resets; it does not fall back to a paid API.
- Free tiers, availability, provider terms, model IDs and quotas can change. Keep the provider accounts on free plans to preserve the zero-API-charge setup.

## Content volume

The pipeline produces at most one video per run and defaults to two uploads per UTC day. A run may publish zero videos if all candidates are stale, scripts fail validation, or items were recently used. The system should not generate low-value posts merely to fill a quota.
