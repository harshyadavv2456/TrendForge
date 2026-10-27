#!/bin/bash
# TrendForge Autonomous Shorts — Local Runner (cache + retry + continuous)
# Runs full pipeline: retry unpublished → discover → download → render → publish
# Never crashes on non-critical errors; always renders from cache if discovery fails.
set -eo pipefail

cd /Users/harshyadav/TrendForge
source .venv/bin/activate
export TRENDFORGE_LOG="/Users/harshyadav/TrendForge/logs/autonomous-$(date +%Y%m%d-%H%M%S).log"

# Load local environment (gitignored, never committed)
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

# ── Step 0: Retry publishing any previously rendered but unpublished clips ──
log "Step 0: Checking for previously rendered unpublished clips..."
PUBLISHED_STATE="data/published.json"
PUBLISHED_PARTS=()
if [ -f "$PUBLISHED_STATE" ]; then
    while IFS= read -r line; do
        [ -n "$line" ] && PUBLISHED_PARTS+=("$line")
    done < <(python3 -c "import json; d=json.load(open('$PUBLISHED_STATE')); print('\n'.join(d.get('published_parts', [])))") || true
fi

unpublished_parts=()
for part_file in outputs/series/part-*.mp4; do
    [ -f "$part_file" ] || continue
    part_name=$(basename "$part_file")
    found=0
    for p in "${PUBLISHED_PARTS[@]}"; do
        if [ "$p" = "$part_name" ]; then
            found=1
            break
        fi
    done
    if [ "$found" -eq 0 ]; then
        unpublished_parts+=("$part_file")
    fi
done

if [ ${#unpublished_parts[@]} -gt 0 ]; then
    log "Found ${#unpublished_parts[@]} unpublished clip(s), attempting publish..."
    python - <<'PY' 2>>"$TRENDFORGE_LOG" || true
import json, os, glob
from pathlib import Path
from trendforge.config import Settings
from trendforge.publisher import upload_short

settings = Settings.from_env()
state_path = Path("data/published.json")
state = json.loads(state_path.read_text()) if state_path.exists() else {"published_parts": []}

manifest_path = Path("outputs/series/series-manifest.json")
manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"source": {}, "parts": []}
source = manifest.get("source", {})

newly_published = []
for part_file in sorted(glob.glob("outputs/series/part-*.mp4")):
    part_name = Path(part_file).name
    if part_name in state["published_parts"]:
        continue
    script = {
        "title": f"{source.get('title','TrendForge')} | Part {Path(part_file).stem}",
        "description": (
            f"{source.get('title','TrendForge')} — Shorts series part from {source.get('creator','Creator')}.\n\n"
            f"Source: {source.get('url','')}\n\n"
            "Original footage clipped into vertical Shorts with attribution."
        )[:4800],
        "tags": ["shorts", "highlight", "clip", str(source.get('creator','Creator'))[:40]],
        "source": {"url": source.get('url',''), "creator": source.get('creator',''), "title": source.get('title','')},
    }
    try:
        result = upload_short(settings, Path(part_file), script, publish=True)
        state["published_parts"].append(part_name)
        newly_published.append(part_name)
        print(f"Published {part_name}: {result['url']} ({result['privacy_status']})")
    except Exception as exc:
        print(f"Publish failed for {part_name}: {exc}")

state_path.write_text(json.dumps(state, indent=2))
if newly_published:
    print(f"Total newly published: {len(newly_published)}")
PY
    log "Publishing complete."
else
    log "No unpublished clips to publish."
fi

# ── Step 1: Discover trending YouTube candidates ──
log "Step 1: Discovering trending candidates..."
SOURCE_URL=""
SOURCE_TITLE=""
SOURCE_CREATOR=""

if [ -z "${YOUTUBE_API_KEY:-}" ]; then
    log "WARNING: YOUTUBE_API_KEY not set. Skipping discovery."
else
    python -m trendforge.discover --count 5 --json > outputs/discovery.json 2>>"$TRENDFORGE_LOG" && \
    python - <<'PY' 2>>"$TRENDFORGE_LOG" || log "WARNING: Discovery parse failed, will use cached source."
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
    if [ -f /tmp/trendforge_source.env ]; then
        set -a
        . /tmp/trendforge_source.env
        set +a
        rm -f /tmp/trendforge_source.env
        log "Selected: $SOURCE_TITLE by $SOURCE_CREATOR ($SOURCE_URL)"
    fi
fi

# ── Step 2: Download source video via yt-dlp (only if not already cached) ──
log "Step 2: Checking source video cache..."
SOURCE_FILE="outputs/source/source-video.mp4"
if [ -f "$SOURCE_FILE" ] && [ -s "$SOURCE_FILE" ]; then
    log "Source video already cached, skipping download."
else
    if [ -z "${SOURCE_URL:-}" ]; then
        log "ERROR: No source URL and no cached video. Cannot render new clips."
        exit 0
    fi
    log "Downloading source video..."
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
fi

# ── Step 3: Build Shorts series (highlight moments with PART overlay) ──
log "Step 3: Building Shorts series..."
rm -rf outputs/series
mkdir -p outputs/series
python -m trendforge.series \
    --input ./outputs/source/source-video.mp4 \
    --output-dir ./outputs/series \
    --source-url "${SOURCE_URL:-}" \
    --title "${SOURCE_TITLE:-TrendForge Source}" \
    --creator "${SOURCE_CREATOR:-Creator}" \
    --rights-confirmed \
    --count 5 \
    --part-seconds 55 \
    --overlay-seconds 2 \
    --groq-api-key "${GROQ_API_KEY:-}" 2>>"$TRENDFORGE_LOG" || {
    log "ERROR: Series build failed. Exiting."
    exit 1
}
log "Series built successfully."

# ── Step 4: Publish new Shorts to YouTube (if auto-publish enabled) ──
if [ "${AUTO_PUBLISH:-false}" = "true" ] && [ -n "${YOUTUBE_REFRESH_TOKEN:-}" ] && [ -n "${YOUTUBE_CLIENT_ID:-}" ] && [ -n "${YOUTUBE_CLIENT_SECRET:-}" ]; then
    log "Step 4: Publishing new Shorts to YouTube..."
    python - <<'PY' 2>>"$TRENDFORGE_LOG" || true
import json, os
from pathlib import Path
from trendforge.config import Settings
from trendforge.publisher import upload_short

settings = Settings.from_env()
state_path = Path("data/published.json")
state = json.loads(state_path.read_text()) if state_path.exists() else {"published_parts": []}

manifest_path = Path("outputs/series/series-manifest.json")
manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"source": {}, "parts": []}
source = manifest.get("source", {})

import glob
newly_published = []
for part_file in sorted(glob.glob("outputs/series/part-*.mp4")):
    part_name = Path(part_file).name
    if part_name in state["published_parts"]:
        continue
    script = {
        "title": f"{source.get('title','TrendForge')} | Part {Path(part_file).stem}",
        "description": (
            f"{source.get('title','TrendForge')} — Shorts series part from {source.get('creator','Creator')}.\n\n"
            f"Source: {source.get('url','')}\n\n"
            "Original footage clipped into vertical Shorts with attribution."
        )[:4800],
        "tags": ["shorts", "highlight", "clip", str(source.get('creator','Creator'))[:40]],
        "source": {"url": source.get('url',''), "creator": source.get('creator',''), "title": source.get('title','')},
    }
    try:
        result = upload_short(settings, Path(part_file), script, publish=True)
        state["published_parts"].append(part_name)
        newly_published.append(part_name)
        print(f"Published {part_name}: {result['url']} ({result['privacy_status']})")
    except Exception as exc:
        print(f"Publish failed for {part_name}: {exc}")

state_path.write_text(json.dumps(state, indent=2))
if newly_published:
    print(f"Total newly published: {len(newly_published)}")
PY
    log "Publishing complete."
else
    log "Step 4: Auto-publish disabled or OAuth not configured. Clips saved locally."
fi

log "=== TrendForge autonomous run completed ==="
