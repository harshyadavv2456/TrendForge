# Configuration reference

Non-secret settings can be supplied as GitHub Actions repository **variables** or local environment variables. API keys and OAuth credentials belong only in GitHub Actions **secrets**. TrendForge uses Groq for script generation and eSpeak NG for local narration; it does not call a paid TTS or LLM endpoint.

| Name | Default | Meaning |
| --- | --- | --- |
| AUTO_PUBLISH | true in the workflow | true uploads after validation; false produces a preview only |
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
| LOCAL_TTS_VOICE | en-us+m3 | eSpeak NG voice; runs locally with no TTS API |
| VIDEO_CATEGORY_ID | 24 | YouTube video category (24 = Entertainment) |
| VIDEO_PRIVACY_STATUS | public | Requested upload privacy; choose private/unlisted if desired |
| VIDEO_LANGUAGE | en | Default language metadata |

## Search strategy

TrendForge uses YouTube's native mostPopular chart order for each configured region, newest uploads from a rotating set of creator channel handles, and recent niche search results ordered by YouTube's viewCount field. Four creator channels and four niche searches run by default at each six-hour interval. This is a quota-aware sample, not an exhaustive crawl of YouTube.

## Ordering and freshness

TrendForge does not calculate a custom cross-channel trend score, view-velocity metric, commercial-fit score, or creator-revenue estimate from YouTube API data. It preserves the API's native order, interleaves source lists, and applies a published-date freshness check. The API response includes only fields needed for discovery; the pipeline does not cache public view counts or put counts in generated videos. The sample video is a separate offline fixture and is explicitly labelled as a demo.

## Free-tier cost controls

- Groq is used for text generation only; keep the account on the Free Plan. When rate limits are reached, the pipeline stops/filters rather than switching to a paid API.
- eSpeak NG synthesizes narration locally; FFmpeg and Pillow create the MP4 locally on a GitHub Actions runner.
- YouTube API usage is quota-limited, not a per-request paid API in this setup. It can stop working until quota resets, and the quota/policies are controlled by Google.
- GitHub-hosted standard runners are free for this public repository. API limits and provider terms can change.

## Content volume

The pipeline produces at most one video per run and defaults to two uploads per UTC day. A run may publish zero videos if all candidates are stale, scripts fail validation, or items were recently used. The system should not generate low-value posts merely to fill a quota.
