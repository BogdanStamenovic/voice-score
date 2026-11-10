#!/usr/bin/env bash
# Run each tracker's benchmark in its own process (pYIN alone takes ~45 min), then merge.
# Usage: bench/run-parallel.sh [VENV_BIN]  (default: the bench venv on /mnt/offload)
set -uo pipefail
BIN="${1:-/mnt/offload/voice-score/bench-venv/bin}"
OUT="$(cd "$(dirname "$0")" && pwd)/results"
TRACKERS="${TRACKERS:-swiftf0 pyin fcpe pesto rmvpe}"
for t in $TRACKERS; do
    mkdir -p "$OUT/$t"
    OMP_NUM_THREADS=2 "$BIN/voice-score" bench --trackers "$t" --out "$OUT/$t" \
        > "$OUT/$t/stdout.log" 2> "$OUT/$t/stderr.log" &
done
wait
"$BIN/python" - "$OUT" $TRACKERS <<'PY'
import json, sys
from pathlib import Path
from voice_score import bench
out = Path(sys.argv[1]); merged = {"trackers": {}}
for t in sys.argv[2:]:
    p = out / t / "results.json"
    if p.exists():
        r = json.loads(p.read_text()); merged["cases"] = r["cases"]; merged["trackers"].update(r["trackers"])
(out / "results.json").write_text(json.dumps(merged, indent=2))
(out / "results.md").write_text(bench.markdown(merged) + "\n")
bench.write_csv(merged, out / "results.csv")
print(bench.markdown(merged))
PY
