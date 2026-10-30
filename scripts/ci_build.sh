#!/usr/bin/env bash
# GitHub Actions compute step: discover + clip, NO upload.
# Output: a GitHub *prerelease* tagged clips-<source_video_id> holding part-NN.mp4 + manifest.json.
# Plus metadata.json: per-clip title/description/tags/hashtags for whoever posts them.
# Posting is done separately; once a series is posted, flip the release to a normal release
# (gh release edit clips-<id> --prerelease=false) so the next series gets built.
# Skips discovery entirely (0 quota units) while QUEUE_MAX_SERIES unpublished series exist.
set -eo pipefail
PY="${PYTHON:-python}"
mkdir -p outputs/source data

PENDING=$(gh release list --limit 100 --json tagName,isPrerelease \
    --jq '[.[] | select(.isPrerelease and (.tagName|startswith("clips-")))] | length')
echo "Unpublished series in queue: $PENDING"
if [ "$PENDING" -ge "${QUEUE_MAX_SERIES:-1}" ]; then
    echo "Queue full; skipping discovery and clipping."
    exit 0
fi

"$PY" -m trendforge.discover --count 10 --json > outputs/discovery.json
EXISTING=$(gh release list --limit 200 --json tagName --jq '.[].tagName' | tr '\n' ' ')
SELECTION="$(EXISTING="$EXISTING" "$PY" - <<'PYEOF'
import json, os, shlex
from pathlib import Path
used = set(os.environ.get("EXISTING", "").split())
for c in json.loads(Path("outputs/discovery.json").read_text() or "[]"):
    if c.get("video_id") and f"clips-{c['video_id']}" not in used:
        for k, v in (("SOURCE_ID", c["video_id"]), ("SOURCE_URL", c["url"]),
                     ("SOURCE_TITLE", c["title"]), ("SOURCE_CREATOR", c["creator"])):
            print(f"{k}={shlex.quote(str(v))}")
        break
PYEOF
)"
[ -n "$SELECTION" ] || { echo "No new candidate."; exit 0; }
eval "$SELECTION"
echo "Selected: $SOURCE_TITLE by $SOURCE_CREATOR ($SOURCE_URL)"

SOURCE_FILE="outputs/source/${SOURCE_ID}.mp4"
OK=0
for CLIENT in ${YTDLP_CLIENTS:-tv_simply android_vr tv web_safari mweb ios web_embedded default}; do
    echo "yt-dlp attempt with player_client=$CLIENT"
    if yt-dlp --no-warnings --no-playlist \
        --extractor-args "youtube:player_client=$CLIENT" \
        --format "best[height<=1080][ext=mp4]/bv*[height<=1080]+ba/best" --merge-output-format mp4 \
        --output "$SOURCE_FILE" "$SOURCE_URL"; then OK=1; break; fi
done
[ "$OK" = 1 ] || { echo "::error::yt-dlp blocked for all player clients"; exit 1; }

BUILD="outputs/series-build/${SOURCE_ID}"
"$PY" -m trendforge.series --input "$SOURCE_FILE" --output-dir "$BUILD" \
    --source-url "$SOURCE_URL" --title "$SOURCE_TITLE" --creator "$SOURCE_CREATOR" \
    --rights-confirmed --count "${SERIES_PARTS:-5}" --part-seconds "${PART_SECONDS:-55}" \
    --groq-api-key "${GROQ_API_KEY:-}" > /dev/null
TRENDFORGE_HOME="$PWD/outputs/release" "$PY" -m trendforge.publish_queue enqueue \
    --source-id "$SOURCE_ID" --series-dir "$BUILD" > /dev/null
DIR="outputs/release/outputs/queue/${SOURCE_ID}"
"$PY" - "$DIR" <<'PYEOF'
import json, sys
from pathlib import Path
from trendforge.metadata import build_script
d = Path(sys.argv[1]); m = json.loads((d / "manifest.json").read_text())
clips = []
for p in m["parts"]:
    s = build_script(m["source"], int(p["part"]), int(p["total"]))
    clips.append({"file": p["path"], "part": p["part"], "total": p["total"],
                  "duration_seconds": p.get("duration_seconds"), "title": s["title"],
                  "description": s["description"], "tags": s["tags"],
                  "categoryId": "24", "selfDeclaredMadeForKids": False})
(d / "metadata.json").write_text(json.dumps({"source": m["source"], "clips": clips}, indent=2, ensure_ascii=False) + "\n")
PYEOF
gh release create "clips-${SOURCE_ID}" --prerelease \
    --title "Clips queue: ${SOURCE_TITLE:0:80}" \
    --notes "Source: $SOURCE_URL by $SOURCE_CREATOR. Not yet posted. See metadata.json for titles/descriptions/tags." \
    "$DIR"/manifest.json "$DIR"/metadata.json "$DIR"/part-*.mp4
echo "Created prerelease clips-${SOURCE_ID}"
