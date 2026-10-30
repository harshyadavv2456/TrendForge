#!/usr/bin/env bash
# TrendForge autonomous runner (local or GitHub Actions).
#   1. If rendered parts are queued -> publish at most UPLOADS_PER_RUN (no discovery).
#   2. If the queue is empty -> discover (~10-20 quota units), download, build series, enqueue, publish 1.
# Uploads go through trendforge.publish_queue only, which enforces MAX_UPLOADS_PER_DAY and the
# Pacific-day quota ledger and stops on quotaExceeded/uploadLimitExceeded.
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRENDFORGE_HOME="${TRENDFORGE_HOME:-$(dirname "$SCRIPT_DIR")}"
export TRENDFORGE_HOME
cd "$TRENDFORGE_HOME"

if [ -f .venv/bin/activate ]; then
    # shellcheck disable=SC1091
    . .venv/bin/activate
fi
if [ -f .env ]; then
    set -a; . ./.env; set +a
fi
PY="${PYTHON:-python3}"
mkdir -p logs outputs/source outputs/queue data
TRENDFORGE_LOG="${TRENDFORGE_LOG:-$TRENDFORGE_HOME/logs/autonomous-$(date +%Y%m%d-%H%M%S).log}"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$TRENDFORGE_LOG"; }

publish_step() {
    if [ "${AUTO_PUBLISH:-false}" = "true" ] && [ -n "${YOUTUBE_REFRESH_TOKEN:-}" ] \
        && [ -n "${YOUTUBE_CLIENT_ID:-}" ] && [ -n "${YOUTUBE_CLIENT_SECRET:-}" ]; then
        log "Publishing up to ${UPLOADS_PER_RUN:-1} queued part(s)..."
        "$PY" -m trendforge.publish_queue publish 2>&1 | tee -a "$TRENDFORGE_LOG" || log "WARNING: publish step failed"
    else
        log "AUTO_PUBLISH disabled or OAuth not configured; parts stay queued."
    fi
}

log "=== TrendForge run started (home: $TRENDFORGE_HOME) ==="
QUEUED="$("$PY" -m trendforge.publish_queue status)"
log "Queued unpublished parts: $QUEUED"

if [ "$QUEUED" -gt 0 ]; then
    publish_step
    log "=== Done (queue drained by one step; discovery skipped) ==="
    exit 0
fi

if [ -z "${YOUTUBE_API_KEY:-}" ]; then
    log "Queue empty and YOUTUBE_API_KEY not set; nothing to do."
    exit 0
fi

log "Queue empty: discovering..."
"$PY" -m trendforge.discover --count 10 --json > outputs/discovery.json 2>>"$TRENDFORGE_LOG" || {
    log "WARNING: discovery failed"; exit 0; }

# Pick the first candidate not already queued or published; emit shell-safe assignments.
SELECTION="$("$PY" - <<'PYEOF'
import json, shlex
from pathlib import Path
cands = json.loads(Path("outputs/discovery.json").read_text() or "[]")
pub = Path("data/published.json")
used = set()
if pub.exists():
    used = {k.split(":")[0] for k in json.loads(pub.read_text()).get("published", {})}
used |= {p.name for p in Path("outputs/queue").glob("*") if p.is_dir()}
for c in cands:
    if c.get("video_id") and c["video_id"] not in used:
        for k, v in (("SOURCE_ID", c["video_id"]), ("SOURCE_URL", c["url"]),
                     ("SOURCE_TITLE", c["title"]), ("SOURCE_CREATOR", c["creator"])):
            print(f"{k}={shlex.quote(str(v))}")
        break
PYEOF
)"
if [ -z "$SELECTION" ]; then
    log "No new candidate found."
    exit 0
fi
eval "$SELECTION"
log "Selected: $SOURCE_TITLE by $SOURCE_CREATOR ($SOURCE_URL)"

SOURCE_FILE="outputs/source/${SOURCE_ID}.mp4"
# Invalidate cached footage from any other source.
find outputs/source -type f ! -name "${SOURCE_ID}.mp4" -delete
if [ ! -s "$SOURCE_FILE" ]; then
    if [ -n "${SOURCE_MEDIA_URL:-}" ]; then
        "$PY" -m trendforge.fetch "$SOURCE_MEDIA_URL" --output "$SOURCE_FILE" --rights-confirmed 2>>"$TRENDFORGE_LOG" || {
            log "ERROR: direct media download failed"; exit 1; }
    else
        yt-dlp --no-warnings --quiet --no-playlist \
            --format "best[height<=1080][ext=mp4]/best[ext=mp4]/best" \
            --output "$SOURCE_FILE" "$SOURCE_URL" 2>>"$TRENDFORGE_LOG" || {
            log "ERROR: yt-dlp download failed."; exit 1; }
    fi
fi

BUILD_DIR="outputs/series-build/${SOURCE_ID}"
rm -rf "$BUILD_DIR"
"$PY" -m trendforge.series \
    --input "$SOURCE_FILE" --output-dir "$BUILD_DIR" \
    --source-url "$SOURCE_URL" --title "$SOURCE_TITLE" --creator "$SOURCE_CREATOR" \
    --rights-confirmed --count "${SERIES_PARTS:-5}" --part-seconds "${PART_SECONDS:-55}" \
    --groq-api-key "${GROQ_API_KEY:-}" >/dev/null 2>>"$TRENDFORGE_LOG" || {
    log "ERROR: series build failed"; exit 1; }
"$PY" -m trendforge.publish_queue enqueue --source-id "$SOURCE_ID" --series-dir "$BUILD_DIR" >/dev/null
rm -rf "$BUILD_DIR" "$SOURCE_FILE"
log "Enqueued $("$PY" -m trendforge.publish_queue status) part(s)."

publish_step
log "=== TrendForge run completed ==="
