"""Singing metrics computed from an f0 contour. Pure numpy; no tracker knowledge.

Conventions: pitches are fractional MIDI numbers (69 = A4), errors are cents
(100 per semitone), positive = sharp.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .trackers import Contour

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_NOTE_RE = re.compile(r"^\s*([A-Ga-g])([#b♯♭]?)(-?\d+)\s*$")
_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

GAP_BRIDGE_S = 0.04  # unvoiced gaps shorter than this inside a note are tracker dropouts
MIN_NOTE_S = 0.10
ONSET_TRIM_S = 0.10  # attack transient excluded from accuracy/stability
SPLIT_SEMITONES = 0.75
SPLIT_HOLD_S = 0.06


class MetricsError(Exception):
    pass


class NothingVoiced(MetricsError):
    pass


def hz_to_midi(hz: np.ndarray | float, a4: float = 440.0) -> np.ndarray:
    return 69.0 + 12.0 * np.log2(np.asarray(hz, dtype=np.float64) / a4)


def midi_to_hz(m: float, a4: float = 440.0) -> float:
    return float(a4 * 2 ** ((m - 69.0) / 12.0))


def note_to_midi(name: str) -> int:
    m = _NOTE_RE.match(name)
    if not m:
        raise MetricsError(f"bad note name {name!r} (expected e.g. C4, F#3, Bb2)")
    letter, acc, octave = m.group(1).upper(), m.group(2), int(m.group(3))
    semis = _PC[letter] + (1 if acc in ("#", "♯") else -1 if acc in ("b", "♭") else 0)
    return 12 * (octave + 1) + semis


def midi_to_note(m: float) -> str:
    n = int(round(m))
    return f"{NOTE_NAMES[n % 12]}{n // 12 - 1}"


def _r(x: float | None, nd: int = 1) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    return round(float(x), nd)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) index pairs of True runs."""
    if mask.size == 0:
        return []
    d = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))


def bridged_voicing(voiced: np.ndarray, hop: float) -> np.ndarray:
    out = voiced.copy()
    max_gap = max(1, int(round(GAP_BRIDGE_S / hop))) if hop > 0 else 1
    for s, e in _runs(~voiced):
        if s > 0 and e < len(voiced) and e - s <= max_gap:
            out[s:e] = True
    return out


@dataclass
class Segment:
    start: int  # frame index, inclusive
    end: int  # exclusive

    def dur(self, hop: float) -> float:
        return (self.end - self.start) * hop


def voiced_spans(c: Contour, min_s: float = MIN_NOTE_S) -> list[Segment]:
    hop = c.hop or 0.01
    v = bridged_voicing(c.voiced, hop)
    return [Segment(s, e) for s, e in _runs(v) if (e - s) * hop >= min_s]


def _interp_midi(c: Contour, a4: float) -> np.ndarray:
    """MIDI contour with short dropouts linearly filled (NaN elsewhere)."""
    m = hz_to_midi(c.f0, a4)
    good = np.isfinite(m)
    if good.sum() >= 2:
        idx = np.arange(len(m))
        fill = bridged_voicing(good, c.hop or 0.01) & ~good
        m[fill] = np.interp(idx[fill], idx[good], m[good])
    return m


def segment_notes(c: Contour, a4: float = 440.0) -> list[Segment]:
    """Split voiced spans into notes where the pitch moves and stays moved."""
    hop = c.hop or 0.01
    m = _interp_midi(c, a4)
    hold = max(2, int(round(SPLIT_HOLD_S / hop)))
    out: list[Segment] = []
    for span in voiced_spans(c):
        seg = m[span.start: span.end]
        k = 5 if len(seg) >= 5 else 1
        smooth = np.array([np.nanmedian(seg[max(0, i - k // 2): i + k // 2 + 1])
                           for i in range(len(seg))])
        start = 0
        ref = smooth[0]
        i = 0
        while i < len(smooth):
            if abs(smooth[i] - ref) > SPLIT_SEMITONES:
                j = i
                while j < len(smooth) and abs(smooth[j] - ref) > SPLIT_SEMITONES:
                    j += 1
                if j - i >= hold:
                    out.append(Segment(span.start + start, span.start + i))
                    start = i
                    ref = float(np.median(smooth[i: min(i + hold, len(smooth))]))
                    i += hold
                    continue
                i = j
                continue
            # slowly track the reference so a long glide does not split on every frame
            ref = 0.98 * ref + 0.02 * smooth[i]
            i += 1
        out.append(Segment(span.start + start, span.end))
    return [s for s in out if s.dur(hop) >= MIN_NOTE_S]


def vibrato(cents: np.ndarray, hop: float) -> dict[str, Any]:
    """Rate (Hz) and extent (+/- cents, i.e. half peak-to-peak) of periodic pitch modulation.

    Detrends with a 0.3 s moving average (removes drift and scoops), then looks for a
    spectral peak in 3-9 Hz. Present when the peak band carries most of the residual
    variance and the extent is at least 15 cents.
    """
    none: dict[str, Any] = {"present": False, "rate_hz": None, "extent_cents": None}
    x = cents[np.isfinite(cents)]
    if hop <= 0 or len(x) * hop < 0.6:
        return none
    w = max(3, int(round(0.3 / hop)) | 1)
    kernel = np.ones(w) / w
    pad = np.pad(x, (w // 2, w // 2), mode="edge")
    resid = x - np.convolve(pad, kernel, mode="valid")
    resid = resid[w // 2: len(resid) - w // 2] if len(resid) > w else resid
    if len(resid) * hop < 0.4:
        return none
    n = len(resid)
    nfft = 1 << max(10, (n * 4 - 1).bit_length())
    spec = np.abs(np.fft.rfft(resid * np.hanning(n), nfft)) ** 2
    freqs = np.fft.rfftfreq(nfft, hop)
    band = (freqs >= 3.0) & (freqs <= 9.0)
    if not band.any() or spec.sum() <= 0:
        return none
    k = np.flatnonzero(band)[np.argmax(spec[band])]
    rate = float(freqs[k])
    near = (freqs >= rate - 1.0) & (freqs <= rate + 1.0)
    above = float(spec[freqs > 0.5].sum())
    frac = float(spec[near].sum()) / above if above > 0 else 0.0
    # extent from the band-limited component: sinusoid amplitude = sqrt(2) * rms
    sp = np.fft.rfft(resid, nfft)
    sp[~near] = 0
    comp = np.fft.irfft(sp, nfft)[:n]
    extent = float(np.sqrt(2) * np.sqrt(np.mean(comp ** 2)))
    present = frac >= 0.5 and extent >= 15.0
    return {"present": bool(present), "rate_hz": _r(rate, 2), "extent_cents": _r(extent, 1),
            "periodicity": _r(frac, 2)}


SMOOTH_S = 0.25  # longer than one vibrato cycle (vibrato is 4-8 Hz, i.e. 125-250 ms)


def smooth(x: np.ndarray, hop: float, win_s: float = SMOOTH_S) -> np.ndarray:
    """NaN-aware centered moving average. Removes vibrato and jitter, keeps wander and drift."""
    # np.convolve(mode="same") returns max(len(x), w) samples, so the kernel must not be
    # longer than the input (short beats at fast tempi produce windows of a few frames).
    w = min(max(1, int(round(win_s / hop)) if hop > 0 else 1), max(1, len(x)))
    ok = np.isfinite(x)
    k = np.ones(w)
    num = np.convolve(np.where(ok, x, 0.0), k, "same")
    den = np.convolve(ok.astype(float), k, "same")
    out = np.full_like(x, np.nan, dtype=np.float64)
    good = ok & (den > 0)
    out[good] = num[good] / den[good]
    return out


def _longest_run(mask: np.ndarray, hop: float) -> float:
    runs = _runs(bridged_voicing(mask, hop))
    return max(((e - s) * hop for s, e in runs), default=0.0)


@dataclass
class Target:
    midi: int | None
    name: str | None
    start: float | None = None
    end: float | None = None
    beats: float | None = None
    rest: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


def parse_targets(items: list[Any]) -> list[Target]:
    out = []
    for i, it in enumerate(items):
        if isinstance(it, (int, float)) and not isinstance(it, bool):
            it = {"midi": it}
        elif isinstance(it, str):
            it = {"note": it}
        if not isinstance(it, dict):
            raise MetricsError(f"targets[{i}] must be an object, note name or MIDI number")
        rest = bool(it.get("rest", False))
        midi: int | None = None
        if not rest:
            if "midi" in it:
                midi = int(round(float(it["midi"])))
            elif "note" in it:
                midi = note_to_midi(str(it["note"]))
            else:
                raise MetricsError(f"targets[{i}] needs 'note', 'midi' or 'rest'")
            if not 0 <= midi <= 127:
                raise MetricsError(f"targets[{i}] MIDI {midi} out of range")
        beats = it.get("beats")
        out.append(Target(midi=midi, name=midi_to_note(midi) if midi is not None else None,
                          start=_f(it.get("start")), end=_f(it.get("end")),
                          beats=float(beats) if beats is not None else None, rest=rest, raw=it))
    return out


def _f(x: Any) -> float | None:
    return None if x is None else float(x)


@dataclass
class Options:
    a4_hz: float = 440.0
    pass_cents: float = 50.0
    octave_agnostic: bool = True
    tempo_bpm: float | None = None


def note_metrics(c: Contour, i0: int, i1: int, target_midi: float | None,
                 opt: Options) -> dict[str, Any]:
    """Metrics for frames [i0, i1). target_midi None = judge against the sung median."""
    hop = c.hop or 0.01
    i0, i1 = max(0, i0), min(len(c.t), i1)
    m_all = _interp_midi(c, opt.a4_hz)[i0:i1]
    voiced = np.isfinite(m_all)
    out: dict[str, Any] = {
        "start": _r(float(c.t[i0]) if i1 > i0 else None, 3),
        "end": _r(float(c.t[i1 - 1]) + hop if i1 > i0 else None, 3),
        "voiced_ratio": _r(float(voiced.mean()) if voiced.size else 0.0, 3),
    }
    if voiced.sum() * hop < 0.05:
        out.update({"sung_note": None, "cents_error": None, "abs_cents_mean": None,
                    "within_50c": None, "within_25c": None, "stability_cents_sd": None, "raw_cents_sd": None,
                    "drift_cents": None, "sustain_s": 0.0, "landed_ratio": 0.0, "onset_s": None, "octave_offset": None,
                    "vibrato": vibrato(np.array([]), hop), "pass": False if target_midi is not None else None,
                    "missing": True})
        return out
    first = int(np.flatnonzero(voiced)[0])
    out["onset_s"] = _r(first * hop, 3)
    # steady part: drop the attack (scoop / onset transient)
    trim = min(int(round(ONSET_TRIM_S / hop)), int(voiced.sum() * 0.2))
    steady_idx = np.flatnonzero(voiced)[trim:]
    steady = m_all[steady_idx]
    sung = float(np.median(steady))
    octave = 0
    ref = sung if target_midi is None else float(target_midi)
    if target_midi is not None and opt.octave_agnostic:
        octave = int(round((sung - target_midi) / 12.0))
        ref = target_midi + 12 * octave
    cents = (steady - ref) * 100.0
    sm_all = smooth(m_all, hop)
    # the smoothing window would smear the attack back in; skip another half window
    half = int(round(SMOOTH_S / 2 / hop))
    sm_steady = sm_all[steady_idx[half:]] if len(steady_idx) > 3 * half else sm_all[steady_idx]
    third = max(1, len(steady) // 3)
    in_tol = np.zeros_like(voiced)
    in_tol[voiced] = np.abs((sm_all[voiced] - ref) * 100.0) <= opt.pass_cents
    err = float(np.median(cents))
    out.update({
        "sung_note": midi_to_note(sung),
        "sung_hz": _r(midi_to_hz(sung, opt.a4_hz), 2),
        "cents_error": _r(err) if target_midi is not None else None,
        "abs_cents_mean": _r(float(np.mean(np.abs(cents)))) if target_midi is not None else None,
        "within_50c": _r(float(np.mean(np.abs(cents) <= 50)), 3) if target_midi is not None else None,
        "within_25c": _r(float(np.mean(np.abs(cents) <= 25)), 3) if target_midi is not None else None,
        # wander of the vibrato-smoothed pitch; raw sd includes vibrato and jitter
        "stability_cents_sd": _r(float(np.std(sm_steady * 100.0))),
        "raw_cents_sd": _r(float(np.std(cents))),
        "drift_cents": _r(float((np.median(sm_steady[-third:]) - np.median(sm_steady[:third])) * 100)),
        "sustain_s": _r(_longest_run(in_tol, hop), 2),
        # longest in-tolerance stretch as a share of the note window: "did it land and stay"
        "landed_ratio": _r(_longest_run(in_tol, hop) / max((i1 - i0) * hop, hop), 3),
        "octave_offset": octave if target_midi is not None else None,
        "vibrato": vibrato(cents, hop),
        "pass": (abs(err) <= opt.pass_cents) if target_midi is not None else None,
    })
    return out


def _range(c: Contour, segs: list[Segment], a4: float) -> dict[str, Any]:
    m = smooth(hz_to_midi(c.f0, a4), c.hop or 0.01)
    vals = np.concatenate([m[s.start:s.end] for s in segs]) if segs else np.array([])
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return {"low_note": None, "high_note": None, "low_hz": None, "high_hz": None,
                "semitones": None}
    lo, hi = np.percentile(vals, [2, 98])
    return {"low_note": midi_to_note(lo), "high_note": midi_to_note(hi),
            "low_hz": _r(midi_to_hz(lo, a4), 1), "high_hz": _r(midi_to_hz(hi, a4), 1),
            "semitones": _r(float(hi - lo), 1)}


def _align(seg_midis: list[float], seg_durs: list[float], targets: list[int],
           octave_agnostic: bool) -> list[list[int]]:
    """Monotonic assignment of sung segments to targets (several segments may merge into one
    target; a target may get none). Returns, per target, the segment indices."""
    n, k = len(seg_midis), len(targets)
    if n == 0:
        return [[] for _ in targets]

    def cost(i: int, j: int) -> float:
        d = seg_midis[i] - targets[j]
        if octave_agnostic:
            d -= 12 * round(d / 12)
        return min(abs(d), 3.0) * seg_durs[i]

    skip_target = 2.0 * float(np.median(seg_durs))  # cost of a missed note
    inf = float("inf")
    # dp[i][j]: best cost with segments < i assigned and segment i-1 assigned to target j-1
    dp = np.full((n + 1, k + 1), inf)
    back = np.zeros((n + 1, k + 1), dtype=int)
    for j in range(k + 1):
        dp[0][j] = skip_target * j
    for i in range(1, n + 1):
        for j in range(1, k + 1):
            best, arg = inf, -1
            # segment i-1 continues target j-1 (same target as the previous segment)
            if dp[i - 1][j] < best:
                best, arg = dp[i - 1][j], j
            # segment i-1 starts target j-1, skipping targets jp..j-2
            for jp in range(j):
                v = dp[i - 1][jp] + skip_target * (j - 1 - jp)
                if v < best:
                    best, arg = v, jp
            dp[i][j] = best + cost(i - 1, j - 1)
            back[i][j] = arg
    jend = int(np.argmin(dp[n] + skip_target * (k - np.arange(k + 1))))
    groups: list[list[int]] = [[] for _ in targets]
    i, j = n, jend
    while i > 0 and j > 0:
        groups[j - 1].insert(0, i - 1)
        j = back[i][j]
        i -= 1
    return groups


def _fit_tempo(c: Contour, targets: list[Target], spb: float, t0: float, opt: Options) -> float:
    """Global tempo factor (singer's beat / written beat) that best lines the sung pitch up with
    the target layout. Per window cost = mean over its frames of min(|cents to target|, 300),
    unvoiced frames 300; windows weigh equally. One global factor cannot make a wrongly pitched
    note look right: the correctly sung notes pin the timing."""
    hop = c.hop or 0.01
    m = _interp_midi(c, opt.a4_hz)
    n = len(m)
    best, best_s = float("inf"), 1.0
    for s in np.arange(0.6, 1.6001, 0.02):
        t, costs = t0, []
        for tg in targets:
            dur = (tg.beats if tg.beats is not None else 1.0) * spb * s
            if not tg.rest and tg.midi is not None:
                i0, i1 = int(round(t / hop)), min(n, int(round((t + dur) / hop)))
                seg = m[i0:i1] if i1 > i0 else np.array([np.nan])
                d = (seg - tg.midi) * 100
                if opt.octave_agnostic:
                    d = d - 1200 * np.round(d / 1200)
                costs.append(float(np.mean(np.where(np.isfinite(d), np.minimum(np.abs(d), 300), 300))))
            t += dur
        if not costs:
            return 1.0
        cost = float(np.mean(costs)) + 10 * abs(np.log(s))  # mild preference for written tempo
        if cost < best:
            best, best_s = cost, float(s)
    return best_s


def _align_untimed(c: Contour, targets: list[Target], notes_segs: list[Segment], opt: Options,
                   emit: Any, warnings: list[str]) -> None:
    hop = c.hop or 0.01
    if len(notes_segs) == 0:
        raise NothingVoiced("no sustained notes detected")
    m = hz_to_midi(c.f0, opt.a4_hz)
    meds = [float(np.nanmedian(m[s.start:s.end])) for s in notes_segs]
    durs = [s.dur(hop) for s in notes_segs]
    order = [i for i, t in enumerate(targets) if not t.rest]
    groups = _align(meds, durs, [targets[i].midi or 0 for i in order], opt.octave_agnostic)
    for gi, ti in enumerate(order):
        g = groups[gi]
        if g:
            emit(ti, targets[ti], notes_segs[g[0]].start, notes_segs[g[-1]].end)
        else:
            emit(ti, targets[ti], 0, 0)
    if len(notes_segs) > len(order) * 2:
        warnings.append(f"sang {len(notes_segs)} note segments for {len(order)} targets; "
                        "alignment may be off")


def analyze(c: Contour, targets: list[Target], opt: Options) -> dict[str, Any]:
    hop = c.hop or 0.01
    spans = voiced_spans(c)
    tempo_ratio: float | None = None
    if not spans:
        raise NothingVoiced("no voiced audio detected")
    notes_segs = segment_notes(c, opt.a4_hz)
    warnings: list[str] = []
    notes: list[dict[str, Any]] = []
    frame = lambda t: int(round(t / hop))
    t_first = float(c.t[spans[0].start])

    def emit(idx: int, tg: Target, i0: int, i1: int) -> None:
        d = note_metrics(c, i0, i1, tg.midi, opt)
        notes.append({"index": idx, "target_note": tg.name, "target_midi": tg.midi, **d})

    sung = [t for t in targets if not t.rest]
    if not targets:
        for idx, s in enumerate(notes_segs):
            d = note_metrics(c, s.start, s.end, None, opt)
            notes.append({"index": idx, "target_note": None, "target_midi": None, **d})
    elif all(t.start is not None for t in sung):
        for idx, tg in enumerate(targets):
            if tg.rest:
                continue
            end = tg.end if tg.end is not None else float(c.t[-1]) + hop
            emit(idx, tg, frame(tg.start or 0.0), frame(end))
    elif any(t.beats is not None for t in targets):
        if not opt.tempo_bpm:
            raise MetricsError("targets use 'beats' but tempo_bpm is missing")
        spb = 60.0 / opt.tempo_bpm
        t = t_first
        # Singers drift from the written tempo (synthetic study, bench/glides.py: a rigid grid
        # misreads correct glides by 35-70 c at +/-25% tempo). Fit one global tempo factor.
        tempo_ratio = _fit_tempo(c, targets, spb, t_first, opt)
        spb *= tempo_ratio
        for idx, tg in enumerate(targets):
            dur = (tg.beats if tg.beats is not None else 1.0) * spb
            if not tg.rest:
                emit(idx, tg, frame(t), frame(t + dur))
            t += dur
    elif len(sung) == 1:
        idx = next(i for i, t in enumerate(targets) if not t.rest)
        emit(idx, sung[0], spans[0].start, spans[-1].end)
    else:
        _align_untimed(c, targets, notes_segs, opt, emit, warnings)

    graded = [n for n in notes if n.get("cents_error") is not None]
    all_stab = [n["stability_cents_sd"] for n in notes if n.get("stability_cents_sd") is not None]
    vib_notes = [n["vibrato"] for n in notes if n["vibrato"]["present"]]
    voiced_s = float(sum(s.dur(hop) for s in spans))
    summary: dict[str, Any] = {
        "voiced_s": _r(voiced_s, 2),
        "range": _range(c, notes_segs, opt.a4_hz),
        "notes_targeted": len(sung),
        "tempo_ratio": _r(tempo_ratio, 2),  # sung beat / written beat; >1 = slower; beats only
        "notes_passed": sum(1 for n in notes if n.get("pass")),
        "mean_abs_cents": _r(float(np.mean([abs(n["cents_error"]) for n in graded])))
        if graded else None,
        "stability_cents_sd": _r(float(np.median(all_stab))) if all_stab else None,
        "longest_sustain_s": _r(max((n["sustain_s"] or 0.0 for n in notes), default=0.0), 2),
        "vibrato": {
            "notes_with_vibrato": len(vib_notes),
            "rate_hz": _r(float(np.median([v["rate_hz"] for v in vib_notes])), 2)
            if vib_notes else None,
            "extent_cents": _r(float(np.median([v["extent_cents"] for v in vib_notes])), 1)
            if vib_notes else None,
        },
    }
    if any(n.get("octave_offset") for n in notes):
        warnings.append("sung in a different octave than the target on some notes "
                        "(octave_agnostic=true: scored against the nearest octave)")
    return {"notes": notes, "summary": summary, "warnings": warnings}
