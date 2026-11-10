"""Sequential speed + memory per tracker on an idle machine (the parallel bench's RTF is
skewed by contention). Usage: <bench venv>/bin/python bench/speed.py [trackers...]"""

from __future__ import annotations

import json
import resource
import subprocess
import sys

CODE = r'''
import json, resource, sys, time
import numpy as np, soxr
from voice_score import bench, trackers
cases = bench.vocadito_suite(noisy_snr=None)[:10]
t0 = time.perf_counter(); tr = trackers.get(sys.argv[1]); load = time.perf_counter() - t0
tr.track(np.zeros(16000, dtype=np.float32) + 1e-4, 16000)
audio = sum(len(c["audio"]) / c["sr"] for c in cases)
t0 = time.perf_counter()
for c in cases:
    tr.track(c["audio"], c["sr"])
dt = time.perf_counter() - t0
x60 = soxr.resample(np.concatenate([c["audio"] for c in cases]), cases[0]["sr"], 16000)[:16000*60].astype(np.float32)
t0 = time.perf_counter(); tr.track(x60, 16000); t60 = time.perf_counter() - t0
print(json.dumps({"tracker": sys.argv[1], "load_s": load, "rtf": dt / audio, "audio_s": audio,
                  "sixty_s_clip_s": t60, "max_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024}))
'''

out = []
for name in sys.argv[1:] or ["swiftf0", "pyin", "fcpe", "pesto", "rmvpe"]:
    p = subprocess.run([sys.executable, "-c", CODE, name], capture_output=True, text=True)
    line = [ln for ln in p.stdout.splitlines() if ln.startswith("{")]
    if not line:
        print(f"{name}: failed\n{p.stderr[-500:]}", file=sys.stderr)
        continue
    out.append(json.loads(line[-1]))
    print(line[-1], flush=True)
json.dump(out, open("bench/results/speed.json", "w"), indent=2)
