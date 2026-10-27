# Configuration reference

All non-secret settings can be supplied as GitHub Actions repository **variables** or local environment variables. The workflow's secret values are separate. YouTube discovery deliberately preserves native API ordering and avoids derived cross-channel scoring.

| Name | Default | Meaning |
| --- | --- | --- |
| AUTO_PUBLISH | false in the workflow by default | true creates a public upload after validation; false produces a preview only |
| MAX_UPLOADS_PER_DAY | 2 | Hard cap based on successful uploads recorded in UTC state |
| MAX_CANDIDATES | 35 | Maximum current-run candidates considered, interleaved across discovery sources |
| MAX_SEARCHES_PER_RUN | 4 | Rotating broad niche searches per execution; controls API quota usage |
| MAX_CREATOR_CHANNELS_PER_RUN | 4 | Number of tracked creator channels checked for latest uploads per execution |
| HISTORY_RETENTION_DAYS | 21 | Retention of short-lived source identifiers/deduplication records (maximum 30 days) |
| MIN_SCRIPT_QUALITY | 70 | Minimum language-model self-score; this is a heuristic gate, not a guarantee |
| YOUTUBE_REGIONS | US, GB, CA, AU | Regions used for popular-video charts; configure as pipe-separated codes |
| YOUTUBE_CREATOR_HANDLES | MrBeast / MarkRober / RyanTrahan / Sidemen / Airrack / Mrwhosetheboss / MKBHD | Creator channel handles; entries separated with a pipe character, without the @ prefix |
| YOUTUBE_SEARCH_QUERIES | niche terms | Search terms rotated across runs; separate entries with a pipe character |
| OPENAI_MODEL | gpt-4o-mini | Model used for original script/metadata generation; use a model available to your API account |
| OPENAI_TTS_MODEL | gpt-4o-mini-tts | Model used for narration |
| OPENAI_TTS_VOICE | coral | Supported voice for the chosen TTS model |
| VIDEO_CATEGORY_ID | 24 | YouTube video category (24 = Entertainment) |
| VIDEO_PRIVACY_STATUS | public | Requested privacy for uploads; start with private until testing is complete |
| MAX_SOURCE_AGE_DAYS | 14 | Reject sources whose published date is older than this window (1–30 days) |
| VIDEO_LANGUAGE | en | Default language metadata |
| OPENAI_TTS_INSTRUCTIONS | production voice instructions | Narration tone |

## Search strategy

TrendForge mixes YouTube's native mostPopular chart order for each region, the latest upload order for a rotating set of actual creator channel handles, and YouTube's native viewCount ordering for recent niche searches. By default, four creator channels and four broad searches are checked per run. Channel IDs are resolved on demand and are not cached. Source lists are interleaved to preserve each endpoint's own order. This is a quota-aware sample, not an exhaustive crawl of YouTube.

## Ordering and freshness

TrendForge does not calculate its own cross-channel trend score, view-velocity metric, commercial-fit score or creator-revenue estimate from YouTube API data. It preserves YouTube's own popular-chart order, latest-upload order, and recent query results ordered by YouTube's viewCount field. It rejects sources outside MAX_SOURCE_AGE_DAYS and interleaves the different source lists so one list cannot fill the whole candidate set. Public view counts are displayed as returned by the API.

## Content volume

Begin with one or two uploads per day. A run may publish zero videos if all candidates are stale, scripts fail validation, or items were recently used. This is intentional; the system should not generate low-value posts just to meet a quota. Raising volume does not guarantee more views and can increase the risk of repetitive content.
