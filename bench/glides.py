"""Glide study for music-trainer V-006: are correctly sung glides graded correctly?

Renders sung renditions of the V-006 glide phrases with SwiftF0-tracked audio, analyzes them
exactly as the trainer requests (beats + tempo, pass_cents = tolerance = 100) and scores them
with the trainer's gradeSing formula (music-trainer src/lib/grading.ts: full credit within
tolerance of cents_error, linear to 0 at 3x tolerance, exercise passes at mean >= 0.6).

Usage: .venv/bin/python bench/glides.py [--out bench/results/glides.json]

History (2026-11-10): the rigid beat grid laid out from the first onset misread correct
glides by 35-70 c when the singer drifted +/-25% from the written tempo; scaling the grid to
the sung span broke when the last note was held long (135 c); the tempo fit
(metrics._fit_tempo) brought every case to 2-5 c. Numbers: bench/results/glides-*.md.
"""

from __future__ import annotations

import argparse
import itertools
import json
from typing import Any

import numpy as np

from voice_score import trackers
from voice_score.metrics import Options, analyze, note_to_midi, parse_targets
from voice_score.synth import render

PHRASES = {  # from music-trainer curriculum/V/V-006.yaml, tempo 60
    "V-006-4 1-5-1": (["G3", "D4", "G3"], [2, 2, 2]),
    "V-006-5 1-3-5-3-1": (["G3", "B3", "D4", "B3", "G3"], [1.5, 1.5, 2, 1.5, 2]),
    "V-006-6 5-1": (["D4", "G3"], [2, 2]),
}
TEMPO = 60.0
TOL = 100.0
PASS = 0.6


def rendition(midis: list[float], beats: list[float], *, glide_s: float, place: float,
              tempo_scale: float, detune: list[float], vibrato: bool, seed: int,
              never_land: bool = False, last_mult: float = 1.0,
              drop_last: bool = False) -> np.ndarray:
    """f0 frames (10 ms). The singer's beat is (60/TEMPO)*tempo_scale. Between notes a glide of
    glide_s seconds (cosine-shaped) sits relative to the note boundary: place 0 = starts at the
    boundary (late, eats the next note's window), 0.5 = centred, 1 = ends at the boundary
    (anticipated). never_land: the whole phrase is one continuous slow slide."""
    rng = np.random.default_rng(seed)
    spb = 60.0 / TEMPO * tempo_scale
    beats = list(beats)
    beats[-1] *= last_mult
    if drop_last:
        midis, beats, detune = midis[:-1], beats[:-1], detune[:-1]
    bounds = np.concatenate([[0.0], np.cumsum(np.asarray(beats) * spb)])
    total = bounds[-1]
    t = np.arange(int(round(total * 100))) / 100
    pitch = np.array([midis[np.searchsorted(bounds, x, side="right") - 1] + detune[
        np.searchsorted(bounds, x, side="right") - 1] / 100 for x in t])
    if never_land:
        # piecewise-linear through the note centres: always moving, never held
        centres = (bounds[:-1] + bounds[1:]) / 2
        tgt = np.array([m + d / 100 for m, d in zip(midis, detune)])
        pitch = np.interp(t, np.concatenate([[0], centres, [total]]),
                          np.concatenate([[tgt[0]], tgt, [tgt[-1]]]))
    else:
        for k in range(1, len(midis)):
            b = bounds[k]
            g0 = b - place * glide_s
            a = midis[k - 1] + detune[k - 1] / 100
            z = midis[k] + detune[k] / 100
            sel = (t >= g0) & (t < g0 + glide_s)
            u = (t[sel] - g0) / glide_s
            pitch[sel] = a + (z - a) * (1 - np.cos(np.pi * u)) / 2
    if vibrato:
        pitch = pitch + 0.35 * np.sin(2 * np.pi * 5.5 * t)
    pitch = pitch + np.cumsum(rng.standard_normal(len(t))) * 0.002  # slow wander
    f0 = 440 * 2 ** ((pitch - 69) / 12)
    return np.concatenate([np.zeros(40), f0, np.zeros(40)])


def grade(result: dict[str, Any], n: int) -> tuple[float, list[float | None]]:
    scores, cents = [], []
    for i in range(n):
        note = next((x for x in result["notes"] if x["index"] == i), None)
        c = None if note is None else note.get("cents_error")
        cents.append(c)
        if c is None:
            scores.append(0.0)
            continue
        a = abs(c)
        scores.append(1.0 if a <= TOL else max(0.0, 1 - (a - TOL) / (2 * TOL)))
    return float(np.mean(scores)), cents


def run() -> dict[str, Any]:
    tr = trackers.get("swiftf0")
    grid = {
        "glide_s": [0.15, 0.3, 0.5, 0.8],
        "place": [0.0, 0.5, 1.0],
        "tempo_scale": [0.8, 0.9, 1.0, 1.1, 1.25],
        "vibrato": [False, True],
    }
    rows = []
    seed = 0
    for pname, (notes, beats) in PHRASES.items():
        midis = [float(note_to_midi(n)) for n in notes]
        targets = [{"midi": m, "beats": b} for m, b in zip(midis, beats)]
        kinds: list[tuple[str, list[float], dict[str, Any]]] = []
        for combo in itertools.product(*grid.values()):
            kinds.append(("correct", midis, dict(zip(grid.keys(), combo))))
        # wrong: top note sung a whole tone flat (P4 instead of P5, or M2 for the 3rd)
        wrong = [m - 2 if m == max(midis) else m for m in midis]
        for combo in itertools.product(grid["glide_s"], grid["place"], [0.9, 1.0, 1.1]):
            kinds.append(("wrong-top-2st", wrong, {"glide_s": combo[0], "place": combo[1],
                                                   "tempo_scale": combo[2], "vibrato": False}))
        for ts in (0.8, 1.0, 1.25):
            for gl in (0.15, 0.5):
                # correct notes, last held twice as long as written
                kinds.append(("long-last", midis, {"glide_s": gl, "place": 0.5, "tempo_scale": ts,
                                                   "vibrato": False, "last_mult": 2.0}))
                # singer stops before the last note
                kinds.append(("drop-last", midis, {"glide_s": gl, "place": 0.5, "tempo_scale": ts,
                                                   "vibrato": False, "drop_last": True}))
        for ts in (0.9, 1.0, 1.1):
            kinds.append(("never-lands", midis, {"glide_s": 0.3, "place": 0.5, "tempo_scale": ts,
                                                 "vibrato": False, "never_land": True}))
        for kind, sung, kw in kinds:
            rng = np.random.default_rng(seed)
            detune = list(rng.uniform(-25, 25, len(midis)))
            f0 = rendition(sung, beats, detune=detune, seed=seed, **kw)
            audio = render(f0, noise_snr_db=25, seed=seed, formants=False).audio
            c = tr.track(audio, 16000)
            res = analyze(c, parse_targets(targets), Options(pass_cents=TOL, tempo_bpm=TEMPO))
            score, cents = grade(res, len(midis))
            cents_all = list(cents)  # per target, incl. a dropped last note (None)
            true = [(s - m) * 100 + d for s, m, d in zip(sung, midis, detune)]
            if kw.get("drop_last"):
                true = true[:-1]
                cents = cents[:-1] if len(cents) > len(true) else cents
            err = [abs(a - b) for a, b in zip(cents, true) if a is not None]
            rows.append({"phrase": pname, "kind": kind, **{k: v for k, v in kw.items()},
                         "abs_cents": [None if x is None else abs(x) for x in cents_all],
                         "within_50c": [n.get("within_50c") for n in res["notes"]],
                         "sustain_s": [n.get("sustain_s") for n in res["notes"]],
                         "landed": {n["index"]: n.get("landed_ratio") for n in res["notes"]},
                         "score": score, "passed": score >= PASS, "cents": cents, "true": true,
                         "est_err": float(np.mean(err)) if err else None, "seed": seed})
            seed += 1
    return {"rows": rows}


def summarize(res: dict[str, Any]) -> str:
    rows = res["rows"]
    out = ["| phrase | rendition | n | pass rate | mean score | mean |cents est - true| |",
           "|---|---|---:|---:|---:|---:|"]
    for pname in PHRASES:
        for kind in ("correct", "wrong-top-2st", "never-lands", "long-last", "drop-last"):
            sel = [r for r in rows if r["phrase"] == pname and r["kind"] == kind]
            e = [r["est_err"] for r in sel if r["est_err"] is not None]
            out.append(f"| {pname} | {kind} | {len(sel)} | {np.mean([r['passed'] for r in sel]):.3f} "
                       f"| {np.mean([r['score'] for r in sel]):.3f} | {np.mean(e):.1f} |")
    corr = [r for r in rows if r["kind"] == "correct"]
    out += ["", "Correct renditions, by condition (all phrases):", "",
            "| factor | value | n | pass rate | mean score | mean |est - true| c |", "|---|---|---:|---:|---:|---:|"]
    for factor in ("glide_s", "place", "tempo_scale", "vibrato"):
        for v in sorted({r[factor] for r in corr}):
            sel = [r for r in corr if r[factor] == v]
            e = [r["est_err"] for r in sel if r["est_err"] is not None]
            out.append(f"| {factor} | {v} | {len(sel)} | {np.mean([r['passed'] for r in sel]):.3f} "
                       f"| {np.mean([r['score'] for r in sel]):.3f} | {np.mean(e):.1f} |")
    out += ["", "Alternative lesson specs (tolerance, pass), pass rate:", "",
            "| tolerance | pass | correct | wrong-top-2st | never-lands |", "|---:|---:|---:|---:|---:|"]
    for tol, ps in ((100, 0.6), (75, 0.6), (75, 0.75), (60, 0.75), (50, 0.6), (50, 0.75)):
        rate = {}
        for kind in ("correct", "wrong-top-2st", "never-lands"):
            sel = [r for r in rows if r["kind"] == kind]
            ok = []
            for r in sel:
                sc = [0.0 if a is None else (1.0 if a <= tol else max(0.0, 1 - (a - tol) / (2 * tol)))
                      for a in r["abs_cents"]]
                ok.append(np.mean(sc) >= ps)
            rate[kind] = np.mean(ok)
        out.append(f"| {tol} | {ps} | {rate['correct']:.3f} | {rate['wrong-top-2st']:.3f} "
                   f"| {rate['never-lands']:.3f} |")
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    a = ap.parse_args()
    res = run()
    if a.out:
        with open(a.out, "w") as fh:
            json.dump(res, fh, indent=1)
    print(summarize(res))
