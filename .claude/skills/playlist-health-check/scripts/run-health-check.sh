#!/bin/bash
set -euo pipefail
HEALTH_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE="$HEALTH_DIR/rotation-state.json"
LOG="$HEALTH_DIR/health-check.log"
REPO_DIR="/tmp/beatify-health-repo"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }

[ ! -f "$STATE" ] && echo '{"playlists":[],"last_checked":{},"last_run":null}' > "$STATE"

log "Cloning repo..."
rm -rf "$REPO_DIR"
git clone --depth=1 --filter=blob:none --sparse https://github.com/mholzi/beatify.git "$REPO_DIR" -q
cd "$REPO_DIR" && git sparse-checkout set custom_components/beatify/playlists && git checkout -q
PLAYLIST_DIR="$REPO_DIR/custom_components/beatify/playlists"

NEXT=$(python3 - "$STATE" "$PLAYLIST_DIR" << 'PYEOF'
import json, sys
from pathlib import Path
with open(sys.argv[1]) as f:
    state = json.load(f)
found = sorted([f.name for f in Path(sys.argv[2]).glob("*.json")] +
               ["community/" + f.name for f in Path(sys.argv[2] + "/community").glob("*.json")])
for p in found:
    if p not in state["playlists"]:
        state["playlists"].append(p)
with open(sys.argv[1], "w") as f:
    json.dump(state, f, indent=2)
checked = state.get("last_checked", {})
never = [p for p in state["playlists"] if p not in checked]
print(never[0] if never else sorted(checked.items(), key=lambda x: x[1])[0][0])
PYEOF
)

log "Checking: $NEXT"

INPUT="$HEALTH_DIR/validate-input.json"
OUTPUT="$HEALTH_DIR/validate-output.json"

python3 - "$PLAYLIST_DIR/$NEXT" "$INPUT" << 'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
entries = []
region_maps = []
for s in data["songs"]:
    artist, title = s["artist"], s["title"]
    for field in ["uri", "uri_youtube_music", "uri_tidal", "uri_deezer", "uri_apple_music"]:
        uri = s.get(field)
        if uri:
            entries.append({"uri": uri, "artist": artist, "title": title})
    # uri_apple_music_by_region is validated separately and in batch — it is
    # frequently a different id from uri_apple_music, so the per-track pass
    # above never sees it.
    regions = s.get("uri_apple_music_by_region")
    if isinstance(regions, dict) and regions:
        region_maps.append({"artist": artist, "title": title, "regions": regions})
with open(sys.argv[2], "w") as f:
    json.dump({"uris": entries, "region_maps": region_maps}, f)
claimed = sum(1 for r in region_maps for v in r["regions"].values() if v)
print(f"  {len(data['songs'])} songs x {len(entries)} URIs total"
      f" + {claimed} claimed region(s) across {len(region_maps)} track(s)")
PYEOF

log "Validating URIs (this takes ~7 min for all platforms)..."
python3 "$HEALTH_DIR/scripts/validate_uris.py" "$INPUT" "$OUTPUT" 2>>"$LOG" || true

SUMMARY=$(python3 -c "
import json
with open('$OUTPUT') as f: r = json.load(f)
s = r['summary']
print(f\"{s['ok']} ok, {s['dead']} dead, {s.get('wrong_track',0)} wrong track, {s.get('error',0)} error, {s.get('unreachable',0)} unreachable / {s['total']} total\")
")
log "Results: $SUMMARY"

REGION_SUMMARY=$(python3 -c "
import json
with open('$OUTPUT') as f: r = json.load(f)
s = r.get('region_summary')
if not s:
    print('')
else:
    print(f\"{s['ok']} ok, {s['dead']} dead, {s.get('wrong_track',0)} wrong track, {s.get('unfilled',0)} unfilled / {s['total']} claimed — {s.get('tracks_affected',0)} track(s) affected\")
")
[ -n "$REGION_SUMMARY" ] && log "Region maps: $REGION_SUMMARY"

TODAY=$(date '+%Y-%m-%d')
python3 - "$STATE" "$NEXT" "$TODAY" << 'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    state = json.load(f)
state["last_checked"][sys.argv[2]] = sys.argv[3]
state["last_run"] = sys.argv[3]
with open(sys.argv[1], "w") as f:
    json.dump(state, f, indent=2)
PYEOF

# Zaehlt Basis-URIs UND Region-Maps. Bis zum 18.08.2026 sah diese Stelle nur
# `summary` — ein Lauf mit toten Region-Eintraegen endete deshalb auf
# "All tracks healthy", zwei Zeilen unter der eigenen Meldung "N dead".
# Aufgefallen an motown-soul-classics (#2194, 8 tote Regionen) und erneut an
# 2000s-pop-anthems (#2223, 7 tote Regionen auf einem Track). Beim ersten Mal
# wurden nur die Daten repariert, nicht die Meldung — daher der zweite Fall.
read -r BASE_ISSUES REGION_ISSUES <<EOF
$(python3 -c "
import json
d = json.load(open('$OUTPUT'))
s = d['summary']
r = d.get('region_summary') or {}
print(s['dead'] + s.get('wrong_track', 0) + s.get('error', 0),
      r.get('dead', 0) + r.get('wrong_track', 0))
")
EOF
ISSUES=$((BASE_ISSUES + REGION_ISSUES))
if [ "$ISSUES" -gt 0 ]; then
  log "Found $ISSUES issue(s) — $BASE_ISSUES on base URIs, $REGION_ISSUES in region maps — pending AI review before creating GitHub issue."
else
  log "All tracks healthy — no issues found."
fi

log "Done."
