#!/bin/bash
# TrendForge Autonomous Shorts - Local Runner
# Runs the full pipeline: discover trending → download → render → publish
# Set up with cron to run every 6 hours for full autonomy.
set -euo pipefail

cd /Users/harshyadav/TrendForge
source .venv/bin/activate
export TRENDFORGE_LOG="/Users/harshyadav/TrendForge/logs/autonomous-$(date +%Y%m%d-%H%M%S).log"

# Load local environment variables (API keys, OAuth tokens, etc.)
if [ -f .env ]; then
    set -a
    . .env
    set +a
fi

mkdir -p logs outputs/source outputs/series data

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$TRENDFORGE_LOG"
}

log "=== TrendForge autonomous run started ==="

# Step 1: Discover trending YouTube candidates
log "Step 1: Discovering trending candidates..."
if [ -z "${YOUTUBE_API_KEY:-}" ]; then
    log "WARNING: YOUTUBE_API_KEY not set. Using fallback demo video."
    SOURCE_URL="https://www.youtube.com/watch?v=jNQXAC9IVRw"
    SOURCE_TITLE="Me at the zoo"
    SOURCE_CREATOR="Jawed Karim"
else
    python -m trendforge.discover --count 5 --json > outputs/discovery.json 2>>"$TRENDFORGE_LOG" || {
        log "ERROR: Discovery failed. Exiting."
        exit 1
    }
    # Parse discovery output into shell variables via a temp file
    python - <<'PY' 2>>"$TRENDFORGE_LOG"
import json, os
with open("outputs/discovery.json") as f:
    cands = json.load(f)
if not cands:
    raise SystemExit("No trending candidates found")
top = cands[0]
with open("/tmp/trendforge_source.env", "w") as out:
    out.write(f'SOURCE_URL="{top["url"]}"\n')
    out.write(f'SOURCE_TITLE="{top["title"]}"\n')
    out.write(f'SOURCE_CREATOR="{top["creator"]}"\n')
PY
    if [ ! -f /tmp/trendforge_source.env ]; then
        log "ERROR: Could not parse discovery output. Exiting."
        exit 1
    fi
    set -a
    . /tmp/trendforge_source.env
    set +a
    rm -f /tmp/trendforge_source.env
fi

log "Selected: $SOURCE_TITLE by $SOURCE_CREATOR ($SOURCE_URL)"

# Step 2: Download source video via yt-dlp (works on local Mac)
log "Step 2: Downloading source video..."
rm -f outputs/source/source-video.mp4
yt-dlp \
    --no-check-certificates \
    --no-warnings \
    --quiet \
    --no-playlist \
    --format "best[height<=720][ext=mp4]/best" \
    --extractor-args "youtube:player_client=android" \
    --output "outputs/source/source-video.%(ext)s" \
    "$SOURCE_URL" 2>>"$TRENDFORGE_LOG" || {
    log "ERROR: yt-dlp download failed. Exiting."
    exit 1
}
log "Download complete."

# Step 3: Build Shorts series (55s parts with PART overlay)
log "Step 3: Building Shorts series..."
rm -rf outputs/series
python -m trendforge.series \
    --input ./outputs/source/source-video.mp4 \
    --output-dir ./outputs/series \
    --source-url "$SOURCE_URL" \
    --title "$SOURCE_TITLE" \
    --creator "$SOURCE_CREATOR" \
    --rights-confirmed \
    --count 5 \
    --part-seconds 55 \
    --overlay-seconds 2 2>>"$TRENDFORGE_LOG" || {
    log "ERROR: Series build failed. Exiting."
    exit 1
}
log "Series built successfully."

# Step 4: Publish to YouTube (if OAuth configured)
if [ -n "${YOUTUBE_REFRESH_TOKEN:-}" ] && [ -n "${YOUTUBE_CLIENT_ID:-}" ] && [ -n "${YOUTUBE_CLIENT_SECRET:-}" ]; then
    log "Step 4: Publishing Shorts to YouTube..."
    python - <<'PY' 2>>"$TRENDFORGE_LOG"
import json, os
from pathlib import Path
from trendforge.config import Settings
from trendforge.publisher import upload_short

settings = Settings.from_env()
manifest_path = Path("outputs/series/series-manifest.json")
manifest = json.loads(manifest_path.read_text())
source = manifest["source"]

for part in manifest["parts"]:
    p = Path(part["path"])
    script = {
        "title": f"{source['title']} | Part {part['part']}/{part['total']}"[:90],
        "description": (
            f"{source['title']} — Part {part['part']} of {part['total']} from {source['creator']}.\n\n"
            f"Source video: {source['url']}\n\n"
            "Original footage clipped into vertical Shorts with attribution."
        )[:4800],
        "tags": ["shorts", "highlight", "clip", source["creator"][:40]],
        "source": {
            "url": source["url"],
            "creator": source["creator"],
            "title": source["title"],
        },
    }
    result = upload_short(settings, p, script, publish=True)
    print(f"Part {part['part']}: {result['url']} ({result['privacy_status']})")
PY
    log "Publishing complete."
else
    log "Step 4: Skipping publish (OAuth secrets not configured locally)."
fi

log "=== TrendForge autonomous run completed ==="
