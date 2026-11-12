"""Write parity fixtures for web/test/parity.mjs: PCM (16 kHz f32), Python SwiftF0 contour,
params and the Python /analyze output. Run with the project venv:
    .venv/bin/python web/test/make-fixtures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from voice_score import bench, trackers
from voice_score.metrics import Options, analyze, parse_targets
from voice_score.service import analyze_audio
from voice_score.audio import Audio
from voice_score.synth import note_sequence, render

OUT = Path(__file__).parent / "fixtures"


def cases() -> list[tuple[str, np.ndarray, dict]]:
    out = []
    f = note_sequence([(60, 1.0), (62, 1.0), (64, 1.5)], gap_s=0.15, vibrato_hz=5.5,
                      vibrato_cents=40, detune_cents=-20)
    out.append(("cde_untimed", render(f, formants=False).audio, {"targets": ["C4", "D4", "E4"]}))
    out.append(("cde_beats", render(f, formants=False).audio,
                {"targets": [{"note": "C4", "beats": 2}, {"note": "D4", "beats": 2},
                             {"note": "E4", "beats": 3}], "tempo_bpm": 120}))
    f = note_sequence([(57, 2.0)], detune_cents=30, scoop_cents=-150, jitter_cents=6)
    out.append(("a3_single", render(f, noise_snr_db=20, formants=False).audio,
                {"targets": [{"note": "A3"}], "pass_cents": 25}))
    f = note_sequence([(48, 1.2)], detune_cents=-40)
    out.append(("octave_low", render(f, formants=False).audio, {"targets": ["C4"]}))
    f = note_sequence([(45, 0.6), (52, 0.6), (64, 0.6), (76, 0.8)], gap_s=0.1)
    out.append(("free_range", render(f, formants=False).audio, {}))
    f = note_sequence([(60 + 2 * (i % 2), 0.075) for i in range(8)])
    out.append(("fast16ths", render(f, formants=False).audio,
                {"targets": [{"midi": 60 + 2 * (i % 2), "beats": 0.25} for i in range(8)],
                 "tempo_bpm": 200}))
    f = note_sequence([(60, 0.8), (0, 0.5), (64, 0.8)])
    out.append(("rest", render(f, formants=False).audio,
                {"targets": [{"note": "C4", "beats": 1.6}, {"rest": True, "beats": 1},
                             {"note": "E4", "beats": 1.6}], "tempo_bpm": 120}))
    # V-006 glides with tempo drift / long last note / wrong top note (exercises the tempo fit)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench"))
    from glides import rendition

    for name, sung, kw in [
        ("glide151_slow", [55, 62, 55], {"tempo_scale": 1.25}),
        ("glide151_longlast", [55, 62, 55], {"tempo_scale": 0.85, "last_mult": 2.0}),
        ("glide151_wrongtop", [55, 60, 55], {"tempo_scale": 1.1}),
    ]:
        f = rendition([float(m) for m in sung], [2, 2, 2], glide_s=0.5, place=0.5,
                      detune=[10.0, -20.0, 5.0], vibrato=True, seed=1, **kw)
        out.append((name, render(f, noise_snr_db=25, formants=False).audio,
                    {"targets": [{"midi": m, "beats": 2} for m in (55, 62, 55)], "tempo_bpm": 60,
                     "pass_cents": 100}))
    f = rendition([55.0, 59.0, 62.0, 59.0, 55.0], [1.5, 1.5, 2, 1.5, 2], glide_s=0.3, place=0.0,
                  detune=[0.0] * 5, vibrato=False, seed=2, tempo_scale=0.8)
    out.append(("glide13531_fast", render(f, formants=False).audio,
                {"targets": [{"midi": m, "beats": b} for m, b in
                             zip((55, 59, 62, 59, 55), (1.5, 1.5, 2, 1.5, 2))], "tempo_bpm": 60,
                 "pass_cents": 100}))
    # level warnings: a quiet take (peaks -50 dBFS) and a noisy one (voice 3 dB over noise)
    f = note_sequence([(50, 2.0)], lead_s=0.6, tail_s=0.6)
    x = render(f, formants=False).audio.astype(np.float64)
    out.append(("quiet_take", (x * 0.003 / np.abs(x).max()).astype(np.float32), {"targets": ["D3"]}))
    x = x * 0.3 / np.abs(x).max()
    v = np.abs(x) > 0
    noisy = x + np.random.default_rng(0).standard_normal(len(x)) * np.sqrt(np.mean(x[v] ** 2) / 10 ** 0.3)
    out.append(("noisy_take", noisy.astype(np.float32), {"targets": ["D3"]}))
    # real singing: first 12 s of three vocadito tracks, untargeted and with their notes
    import soxr

    for case in [c for c in bench.vocadito_suite(noisy_snr=None)][:3]:
        x = soxr.resample(case["audio"], case["sr"], 16000).astype(np.float32)[: 16000 * 12]
        name = case["name"].split("/")[0]
        out.append((f"{name}_free", x, {}))
        if case.get("notes") is not None:
            notes = [n for n in case["notes"] if n[0] + n[2] < 12]
            tg = [{"midi": float(69 + 12 * np.log2(p / 440)), "start": float(s),
                   "end": float(s + d)} for s, p, d in notes]
            out.append((f"{name}_timed", x, {"targets": tg}))
            out.append((f"{name}_untimed", x, {"targets": [{"midi": t["midi"]} for t in tg]}))
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tr = trackers.get("swiftf0")
    index = []
    for name, pcm, params in cases():
        pcm = np.ascontiguousarray(pcm, dtype=np.float32)
        (OUT / f"{name}.f32").write_bytes(pcm.tobytes())
        c = tr.track(pcm, 16000)
        p = {**params, "contour": False}
        expected = analyze_audio(Audio(pcm, 16000), p)
        # metrics parity is checked on the exact contour, independent of tracker numerics
        direct = analyze(c, parse_targets(list(params.get("targets") or [])), Options(
            a4_hz=float(params.get("a4_hz", 440)), pass_cents=float(params.get("pass_cents", 50)),
            octave_agnostic=bool(params.get("octave_agnostic", True)),
            tempo_bpm=float(params["tempo_bpm"]) if params.get("tempo_bpm") else None))
        (OUT / f"{name}.json").write_text(json.dumps({
            "name": name, "params": p,
            "contour": {"t": c.t.tolist(), "f0": [None if not np.isfinite(v) else float(v) for v in c.f0]},
            "expected": {"notes": direct["notes"], "summary": direct["summary"],
                         "warnings": direct["warnings"]},
            "expected_service": expected,
        }))
        index.append(name)
    (OUT / "index.json").write_text(json.dumps(index))
    print(f"wrote {len(index)} fixtures to {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
