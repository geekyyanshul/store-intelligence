#!/usr/bin/env bash
# pipeline/run.sh
# One command to process CCTV clips and emit events to the API.
#
# Usage:
#   bash pipeline/run.sh --clip data/clip1.mp4 --store STORE_BLR_002
#   bash pipeline/run.sh --dir data/ --store STORE_BLR_002 --api http://localhost:8000
#   bash pipeline/run.sh --clip data/clip1.mp4 --store STORE_BLR_002 --layout store_layout.json

set -euo pipefail

API_URL="http://localhost:8000"
STORE_ID="STORE_BLR_002"
CAMERA_ID="CAM_01"
LAYOUT=""
CLIP=""
DIR=""
OUTPUT="pipeline/output/events.jsonl"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --clip)     CLIP="$2"; shift 2 ;;
        --dir)      DIR="$2"; shift 2 ;;
        --store)    STORE_ID="$2"; shift 2 ;;
        --camera)   CAMERA_ID="$2"; shift 2 ;;
        --api)      API_URL="$2"; shift 2 ;;
        --layout)   LAYOUT="$2"; shift 2 ;;
        --output)   OUTPUT="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

mkdir -p "$(dirname "$OUTPUT")"

run_clip() {
    local clip="$1"
    local cam="$2"
    echo "Processing: $clip (camera: $cam, store: $STORE_ID)"
    python3 -c "
import sys
sys.path.insert(0, '.')
from pipeline.detect import load_model, process_video
from pipeline.tracker import StoreLayout, VisitorTracker
from pipeline.emit import emit_events, print_events
from datetime import datetime, timezone

model = load_model()
layout = StoreLayout('$LAYOUT' if '$LAYOUT' else None)
tracker = VisitorTracker('$STORE_ID', '$cam', layout)

frames = process_video('$clip', model)
base_time = datetime.now(timezone.utc)
all_events = []
for frame in frames:
    events = tracker.process_frame(frame, base_time)
    all_events.extend(events)

print_events(all_events)
result = emit_events(all_events, '$API_URL', '$OUTPUT')
print(f'Done: {result}', file=sys.stderr)
"
}

if [[ -n "$CLIP" ]]; then
    run_clip "$CLIP" "$CAMERA_ID"
elif [[ -n "$DIR" ]]; then
    idx=1
    for clip in "$DIR"/*.mp4 "$DIR"/*.avi "$DIR"/*.mov; do
        [[ -f "$clip" ]] || continue
        run_clip "$clip" "CAM_$(printf '%02d' $idx)"
        ((idx++))
    done
else
    echo "Error: provide --clip <file> or --dir <directory>"
    exit 1
fi

echo "Events written to: $OUTPUT"
