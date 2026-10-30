#!/usr/bin/env bash
# Scheduled CI job: trending data -> original motion-graphics Short -> clips-<id> prerelease.
# No YouTube downloads, no uploads. Exits 0 on "nothing to do".
set -eo pipefail
PY="${PYTHON:-python}"
mkdir -p data outputs
PENDING=$(gh release list --limit 100 --json tagName,isPrerelease \
    --jq '[.[] | select(.isPrerelease and (.tagName|startswith("clips-")))] | length')
echo "Unposted clips in queue: $PENDING"
if [ "$PENDING" -ge "${QUEUE_MAX_SERIES:-3}" ]; then echo "Queue full; skipping."; exit 0; fi
SKIP_IDS="$(gh release list --limit 200 --json tagName --jq '.[].tagName' | sed -n 's/^clips-//p' | tr '\n' ' ')"
export SKIP_IDS
VID="$("$PY" -m trendforge.original_job | tail -n 1)" || { echo "::warning::original job failed"; exit 0; }
DIR="outputs/release/$VID"
if [ -z "$VID" ] || [ ! -f "$DIR/short.mp4" ]; then echo "Nothing rendered this run."; exit 0; fi
TITLE="$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1]))["clips"][0]["title"])' "$DIR/metadata.json")"
gh release create "clips-$VID" --prerelease --title "Short: $TITLE" \
    --notes "Original motion-graphics Short about https://www.youtube.com/watch?v=$VID . Not yet posted. See metadata.json." \
    "$DIR/short.mp4" "$DIR/metadata.json"
echo "Created prerelease clips-$VID"
