"""Head-to-head pitch tracker benchmark on identical inputs.

Datasets:
  synth     synthetic voice with exactly known f0 (vibrato, scoops, jitter, breath,
            white noise at several SNRs, range A2..C6)
  vocadito  40 solo singing excerpts with annotated f0 (CC BY 4.0, zenodo 5578807),
            clean and with added pink noise at 10 dB SNR

Frame metrics (on ground-truth frames, est resampled to the GT grid):
  RPA   raw pitch accuracy: GT-voiced frames whose estimate is voiced and within 50 cents
  RCA   same, ignoring octave errors
  VR    voicing recall, VFA voicing false alarm
  MAE   median |cents| on frames voiced in both
  P95   95th percentile |cents| on frames voiced in both
Note metric (vocadito): per annotated note, |median est cents - median GT cents| over the
note's frames; this is the error a tracker adds to the grade the trainer shows.
Speed: real-time factor on this CPU (seconds of compute per second of audio).
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from . import trackers
from .synth import SR, note_sequence, render

VOCADITO = Path("/mnt/windows/voice-score-data/dl/vocadito")


def _cents(hz: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return 1200 * np.log2(hz / 10.0)


def resample_to(c: trackers.Contour, t_ref: np.ndarray) -> np.ndarray:
    """Estimated f0 (Hz, NaN unvoiced) at reference times; nearest frame for voicing,
    linear in cents between voiced neighbours."""
    if len(c.t) == 0:
        return np.full(len(t_ref), np.nan)
    idx = np.clip(np.searchsorted(c.t, t_ref), 1, len(c.t) - 1)
    left, right = idx - 1, idx
    nearest = np.where(np.abs(c.t[left] - t_ref) <= np.abs(c.t[right] - t_ref), left, right)
    cents = _cents(c.f0)
    a, b = cents[left], cents[right]
    w = np.clip((t_ref - c.t[left]) / np.maximum(c.t[right] - c.t[left], 1e-9), 0, 1)
    interp = np.where(np.isfinite(a) & np.isfinite(b), a + w * (b - a), cents[nearest])
    out = np.where(np.isfinite(cents[nearest]), 10 * 2 ** (interp / 1200), np.nan)
    out[(t_ref < c.t[0] - 0.05) | (t_ref > c.t[-1] + 0.05)] = np.nan
    return out


def frame_metrics(gt: np.ndarray, est: np.ndarray) -> dict[str, float]:
    gv = gt > 0
    ev = np.isfinite(est)
    both = gv & ev
    err = _cents(est[both]) - _cents(gt[both])
    chroma = np.abs((err + 600) % 1200 - 600)
    n_gv = max(int(gv.sum()), 1)
    good = int(np.sum(np.abs(err) <= 50)) + int(np.sum(~gv & ~ev))
    return {
        "frames": int(gv.sum()),
        "OA": float(good / max(len(gt), 1)),
        "RPA": float(np.sum(np.abs(err) <= 50) / n_gv),
        "RCA": float(np.sum(chroma <= 50) / n_gv),
        "VR": float(both.sum() / n_gv),
        "VFA": float(np.sum(ev & ~gv) / max(int((~gv).sum()), 1)),
        "MAE": float(np.median(np.abs(err))) if err.size else float("nan"),
        "P95": float(np.percentile(np.abs(err), 95)) if err.size else float("nan"),
    }


def synth_suite() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    phrases: dict[str, list[tuple[float, float]]] = {
        # A2-E3 (male low), A3-G4 (middle), A4-C6 (high / falsetto / head voice)
        "low": [(45, 0.8), (47, 0.6), (49, 0.6), (52, 1.0), (50, 0.6), (45, 1.0)],
        "mid": [(57, 0.8), (60, 0.6), (64, 0.6), (62, 0.6), (67, 1.2), (65, 0.8)],
        "high": [(69, 0.8), (72, 0.6), (76, 0.6), (79, 0.8), (84, 1.0), (81, 0.8)],
    }
    styles: dict[str, dict[str, Any]] = {
        "plain": {},
        "vibrato": {"vibrato_hz": 5.8, "vibrato_cents": 50},
        "scoop_jitter": {"scoop_cents": -120, "jitter_cents": 8},
    }
    noises: dict[str, dict[str, Any]] = {
        "clean": {}, "snr20": {"noise_snr_db": 20}, "snr10": {"noise_snr_db": 10},
        "snr5": {"noise_snr_db": 5}, "breathy": {"breath": 0.15, "noise_snr_db": 20},
    }
    seed = 0
    for pname, notes in phrases.items():
        for sname, style in styles.items():
            f0 = note_sequence(notes, gap_s=0.12, seed=seed, **style)
            for nname, noise in noises.items():
                s = render(f0, seed=seed, **noise)
                cases.append({"name": f"{pname}/{sname}/{nname}", "group": f"synth-{nname}",
                              "register": pname,
                              "audio": s.audio, "sr": s.sr, "t": s.t, "f0": s.f0})
                seed += 1
    return cases


def _pink(n: int, rng: np.random.Generator) -> np.ndarray:
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n)
    f[0] = f[1]
    return np.fft.irfft(spec / np.sqrt(f), n)


def vocadito_suite(noisy_snr: float | None = 10.0) -> list[dict[str, Any]]:
    import soundfile as sf

    if not (VOCADITO / "Audio").is_dir():
        print(f"bench: vocadito not found at {VOCADITO}; skipping", file=sys.stderr)
        return []
    rng = np.random.default_rng(0)
    cases = []
    for wav in sorted((VOCADITO / "Audio").glob("vocadito_*.wav"),
                      key=lambda p: int(p.stem.split("_")[1])):
        tid = wav.stem
        gt = np.loadtxt(VOCADITO / "Annotations/F0" / f"{tid}_f0.csv", delimiter=",")
        notes_path = VOCADITO / "Annotations/Notes" / f"{tid}_notesA1.csv"
        notes = np.loadtxt(notes_path, delimiter=",", ndmin=2) if notes_path.exists() else None
        audio, sr = sf.read(wav, dtype="float32", always_2d=False)
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        base = {"t": gt[:, 0], "f0": gt[:, 1], "sr": sr, "notes": notes}
        cases.append({"name": f"{tid}/clean", "group": "vocadito-clean", "audio": audio, **base})
        if noisy_snr is not None:
            p = float(np.mean(audio[np.abs(audio) > 0.01] ** 2)) if np.any(np.abs(audio) > 0.01) \
                else float(np.mean(audio ** 2))
            noise = _pink(len(audio), rng)
            noise *= np.sqrt(p / 10 ** (noisy_snr / 10) / np.mean(noise ** 2))
            cases.append({"name": f"{tid}/pink{noisy_snr:g}", "group": f"vocadito-pink{noisy_snr:g}",
                          "audio": (audio + noise).astype(np.float32), **base})
    return cases


def note_errors(case: dict[str, Any], est: np.ndarray) -> list[float]:
    notes = case.get("notes")
    if notes is None:
        return []
    t, gt = case["t"], case["f0"]
    out = []
    for start, _pitch, dur in notes:
        m = (t >= start + 0.05) & (t < start + dur - 0.05) & (gt > 0)
        if m.sum() < 5:
            continue
        g = np.median(_cents(gt[m]))
        e = est[m]
        e = e[np.isfinite(e)]
        out.append(float(abs(np.median(_cents(e)) - g)) if e.size >= 3 else float("inf"))
    return out


def _with_threshold(c: trackers.Contour, th: float) -> trackers.Contour:
    raw = c.raw_f0 if c.raw_f0 is not None else c.f0
    return trackers.Contour(c.t, np.where(c.confidence >= th, raw, np.nan), c.confidence, raw, th)


def _evaluate(cases: list[dict[str, Any]], contours: list[trackers.Contour],
              th: float | None) -> dict[str, float]:
    rows, notes = [], []
    for case, c in zip(cases, contours):
        est = resample_to(c if th is None else _with_threshold(c, th), case["t"])
        rows.append(frame_metrics(case["f0"], est))
        notes.extend(note_errors(case, est))
    ne = np.array(notes)
    return {"OA": float(np.mean([r["OA"] for r in rows])),
            "RPA": float(np.mean([r["RPA"] for r in rows])),
            "VFA": float(np.mean([r["VFA"] for r in rows])),
            "note_mae": float(np.median(ne[np.isfinite(ne)])) if ne.size else float("nan"),
            "note_within_25c": float(np.mean(ne <= 25)) if ne.size else float("nan")}


def sweep(cases: list[dict[str, Any]], contours: list[trackers.Contour]) -> dict[str, Any]:
    """Tune the voicing threshold for overall accuracy on odd vocadito tracks, report it on the
    even (held-out) tracks next to the tracker's default operating point."""
    def pick(group: str, parity: int) -> tuple[list[dict[str, Any]], list[trackers.Contour]]:
        sel = [(a, c) for a, c in zip(cases, contours) if a["group"] == group
               and int(a["name"].split("/")[0].split("_")[1]) % 2 == parity]
        return [a for a, _ in sel], [c for _, c in sel]

    tune_cases, tune_c = pick("vocadito-clean", 1)
    if not tune_cases:
        return {}
    conf = np.concatenate([c.confidence for c in tune_c])
    grid = np.unique(np.concatenate([np.quantile(conf, np.linspace(0.02, 0.98, 49)),
                                     [tc.threshold for tc in tune_c[:1]]]))
    scores = [(_evaluate(tune_cases, tune_c, float(th))["OA"], float(th)) for th in grid]
    best_oa, best_th = max(scores)
    out: dict[str, Any] = {"threshold_default": tune_c[0].threshold, "threshold_tuned": best_th,
                           "tune_OA": best_oa}
    for group in ("vocadito-clean", "vocadito-pink10"):
        test_cases, test_c = pick(group, 0)
        if test_cases:
            out[group] = {"default": _evaluate(test_cases, test_c, None),
                          "tuned": _evaluate(test_cases, test_c, best_th)}
    return out


def run(names: list[str], datasets: list[str], out: Path | None) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    if "synth" in datasets:
        cases += synth_suite()
    if "vocadito" in datasets:
        cases += vocadito_suite()
    results: dict[str, Any] = {"cases": len(cases), "trackers": {}}
    for name in names:
        try:
            tr = trackers.get(name)
        except trackers.TrackerUnavailable as exc:
            print(f"bench: {exc}", file=sys.stderr)
            continue
        if hasattr(tr, "sweep"):
            tr.sweep = True  # FCPE: derive a confidence from its threshold grid
        tr.track(np.zeros(SR, dtype=np.float32) + 1e-4, SR)  # warm-up (graph init, JIT)
        per_group: dict[str, list[dict[str, float]]] = {}
        notes_err: dict[str, list[float]] = {}
        compute = audio_s = 0.0
        contours: list[trackers.Contour] = []
        for case in cases:
            t0 = time.perf_counter()
            c = tr.track(case["audio"], case["sr"])
            contours.append(c)
            compute += time.perf_counter() - t0
            audio_s += len(case["audio"]) / case["sr"]
            est = resample_to(c, case["t"])
            fm = frame_metrics(case["f0"], est)
            per_group.setdefault(case["group"], []).append(fm)
            if "register" in case:  # synthetic cases also aggregate by register
                per_group.setdefault(f"synth-{case['register']}", []).append(fm)
            notes_err.setdefault(case["group"], []).extend(note_errors(case, est))
        groups = {}
        for g, rows in sorted(per_group.items()):
            w = np.array([r["frames"] for r in rows], dtype=float)
            agg = {k: float(np.nansum([r[k] * wi for r, wi in zip(rows, w)]) / w.sum())
                   for k in ("RPA", "RCA", "VR", "VFA")}
            agg["OA"] = float(np.mean([r["OA"] for r in rows]))
            agg["MAE"] = float(np.nanmedian([r["MAE"] for r in rows]))
            agg["P95"] = float(np.nanmedian([r["P95"] for r in rows]))
            ne = np.array(notes_err.get(g, []))
            if ne.size:
                agg["notes"] = int(ne.size)
                agg["note_mae"] = float(np.median(ne[np.isfinite(ne)]))
                agg["note_within_10c"] = float(np.mean(ne <= 10))
                agg["note_within_25c"] = float(np.mean(ne <= 25))
            groups[g] = agg
        results["trackers"][name] = {"rtf": compute / audio_s, "audio_s": audio_s,
                                     "groups": groups, "sweep": sweep(cases, contours)}
        print(f"bench: {name} done, RTF {compute / audio_s:.4f}", file=sys.stderr)
    if out:
        out.write_text(json.dumps(results, indent=2))
    return results


def markdown(results: dict[str, Any]) -> str:
    lines = []
    groups = sorted({g for r in results["trackers"].values() for g in r["groups"]})
    lines.append("| tracker | RTF | " + " | ".join(f"{g} RPA" for g in groups) + " |")
    lines.append("|---|---:|" + "---:|" * len(groups))
    for name, r in results["trackers"].items():
        cells = [f"{r['groups'][g]['RPA']:.3f}" if g in r["groups"] else "-" for g in groups]
        lines.append(f"| {name} | {r['rtf']:.4f} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("| tracker | group | OA | RPA | RCA | VR | VFA | MAE c | P95 c | note MAE c | notes <=10c | notes <=25c |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, r in results["trackers"].items():
        for g in groups:
            a = r["groups"].get(g)
            if not a:
                continue
            nm = (f"{a['note_mae']:.1f} | {a['note_within_10c']:.3f} | {a['note_within_25c']:.3f}"
                  if "note_mae" in a else "- | - | -")
            lines.append(f"| {name} | {g} | {a.get('OA', float('nan')):.3f} | {a['RPA']:.3f} | {a['RCA']:.3f} | {a['VR']:.3f} | "
                         f"{a['VFA']:.3f} | {a['MAE']:.1f} | {a['P95']:.1f} | {nm} |")
    lines.append("")
    lines.append("Voicing threshold tuned for OA on odd vocadito tracks, scored on even tracks:")
    lines.append("")
    lines.append("| tracker | group | threshold | OA | RPA | VFA | note MAE c | notes <=25c |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    for name, r in results["trackers"].items():
        sw = r.get("sweep") or {}
        for g in ("vocadito-clean", "vocadito-pink10"):
            for kind in ("default", "tuned"):
                a = (sw.get(g) or {}).get(kind)
                if not a:
                    continue
                th = sw["threshold_default" if kind == "default" else "threshold_tuned"]
                lines.append(f"| {name} | {g} | {kind} {th:.3g} | {a['OA']:.3f} | {a['RPA']:.3f} "
                             f"| {a['VFA']:.3f} | {a['note_mae']:.1f} | {a['note_within_25c']:.3f} |")
    return "\n".join(lines)


def write_csv(results: dict[str, Any], path: Path) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tracker", "group", "RPA", "RCA", "VR", "VFA", "MAE", "P95", "note_mae",
                    "note_within_10c", "note_within_25c", "rtf"])
        for name, r in results["trackers"].items():
            for g, a in r["groups"].items():
                w.writerow([name, g] + [round(a.get(k, float("nan")), 4) for k in
                                        ("RPA", "RCA", "VR", "VFA", "MAE", "P95", "note_mae",
                                         "note_within_10c", "note_within_25c")]
                           + [round(r["rtf"], 5)])
