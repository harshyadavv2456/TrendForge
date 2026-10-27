# Configuration reference

All settings can be supplied as GitHub Actions repository **variables** or local environment variables. The workflow's secret values are separate.

| Name | Default | Meaning |
| --- | --- | --- |
| AUTO_PUBLISH | false in the workflow by default | true creates a public upload after validation; false produces a preview only |
| MAX_UPLOADS_PER_DAY | 2 | Hard cap based on successful uploads recorded in UTC state |
| MIN_TREND_SCORE | 42 | Minimum ranking score out of 100 before a script is generated |
| MAX_CANDIDATES | 35 | Candidate metadata records retained for scoring/reporting |
| MAX_SEARCHES_PER_RUN | 4 | Rotating broad niche searches per execution; controls API quota usage |
| MAX_CREATOR_CHANNELS_PER_RUN | 4 | Number of tracked creator channels checked for latest uploads per execution |
| HISTORY_RETENTION_DAYS | 45 | Retention of public trend snapshots, generated items and upload records |
| MIN_SCRIPT_QUALITY | 70 | Minimum language-model self-score; this is a heuristic gate, not a guarantee |
| YOUTUBE_REGIONS | US|GB|CA|AU | Regions used for popular-video charts |
| YOUTUBE_CREATOR_HANDLES | MrBeast, MarkRober, RyanTrahan, Sidemen, Airrack, Mrwhosetheboss, MKBHD | Creator channel handles; entries separated with a pipe character, without the @ prefix |
| YOUTUBE_SEARCH_QUERIES | niche terms | Search terms rotated across runs; separate entries with a pipe character |
| OPENAI_MODEL | gpt-4o-mini | Model used for original script/metadata generation; use a model available to your API account |
| OPENAI_TTS_MODEL | gpt-4o-mini-tts | Model used for narration |
| OPENAI_TTS_VOICE | coral | Supported voice for the chosen TTS model |
| VIDEO_CATEGORY_ID | 24 | YouTube video category (24 = Entertainment) |
| VIDEO_PRIVACY_STATUS | public | Requested privacy for uploads; start with private until testing is complete |
| VIDEO_LANGUAGE | en | Default language metadata |
| OPENAI_TTS_INSTRUCTIONS | production voice instructions | Narration tone |

## Search strategy

TrendForge mixes YouTube's most-popular chart for each configured region, latest uploads from a rotating set of actual channel handles, and recent-video searches across niches. It resolves handles to channel IDs and caches the IDs in data/state.json. By default, four creator channels and four broad searches are checked each run; every configured creator is revisited as the cursor rotates. This is deliberately a quota-aware sample, not an exhaustive crawl of YouTube. Configure YOUTUBE_CREATOR_HANDLES and YOUTUBE_SEARCH_QUERIES as pipe-separated values.

## Ranking model

The score is a heuristic combining estimated recent view velocity, freshness, total views, engagement signals, creator-topic relevance and region presence. When the same public video is observed in later runs, the system uses the change in public view count as one velocity signal. On the first observation, views divided by age is only a rough proxy. The score is not a view/revenue prediction.

## Content volume

Begin with one or two uploads per day. A run may publish zero videos if all candidates are stale, scores are too low, scripts fail validation, or items were recently used. This is intentional; the system should not generate low-value posts just to meet a quota. Raising volume does not guarantee more views and can increase the risk of repetitive content.
