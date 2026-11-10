"""Synthetic singing-like test signals with exactly known f0 (for tests and the benchmark)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SR = 16000


@dataclass
class Synth:
    audio: np.ndarray
    sr: int
    t: np.ndarray  # ground-truth frame times (10 ms)
    f0: np.ndarray  # Hz, 0 = unvoiced


def _formant_filter(x: np.ndarray, sr: int) -> np.ndarray:
    """Crude /a/ vowel: three resonators, so the spectrum is not a flat harmonic comb."""
    from scipy.signal import lfilter  # optional (bench extra); render() skips formants without it

    for fc, bw in ((700, 110), (1220, 120), (2600, 160)):
        r = np.exp(-np.pi * bw / sr)
        th = 2 * np.pi * fc / sr
        x = lfilter([1 - r], [1, -2 * r * np.cos(th), r * r], x)
    return x


def render(f0_frames: np.ndarray, sr: int = SR, hop_s: float = 0.01, harmonics: int = 20,
           noise_snr_db: float | None = None, breath: float = 0.0, formants: bool = True,
           seed: int = 0) -> Synth:
    """Additive harmonic voice following f0_frames (Hz per 10 ms frame, 0 = silence)."""
    rng = np.random.default_rng(seed)
    n = int(len(f0_frames) * hop_s * sr)
    ft = np.arange(len(f0_frames)) * hop_s
    st = np.arange(n) / sr
    f0 = np.interp(st, ft, f0_frames)
    voiced = f0 > 0
    # amplitude envelope with 15 ms ramps at voicing edges, avoids clicks
    env = np.convolve(voiced.astype(float), np.ones(int(0.015 * sr)) / int(0.015 * sr), "same")
    phase = 2 * np.pi * np.cumsum(f0) / sr
    x = np.zeros(n)
    for h in range(1, harmonics + 1):
        amp = 1.0 / h ** 1.2
        x += amp * np.sin(h * phase) * (h * f0 < sr / 2 - 200)
    x *= env
    if breath > 0:
        x += breath * rng.standard_normal(n) * env
    if formants:
        try:
            x = _formant_filter(x, sr)
        except ImportError:
            pass
    x = 0.3 * x / (np.max(np.abs(x)) + 1e-9)
    if noise_snr_db is not None:
        p_sig = np.mean(x[voiced] ** 2) if voiced.any() else 1e-6
        x = x + rng.standard_normal(n) * np.sqrt(p_sig / 10 ** (noise_snr_db / 10))
    return Synth(x.astype(np.float32), sr, ft, np.asarray(f0_frames, dtype=float))


def note_sequence(notes: list[tuple[float, float]], a4: float = 440.0, gap_s: float = 0.0,
                  lead_s: float = 0.3, tail_s: float = 0.3, vibrato_hz: float = 0.0,
                  vibrato_cents: float = 0.0, detune_cents: float = 0.0,
                  scoop_cents: float = 0.0, jitter_cents: float = 0.0, seed: int = 0) -> np.ndarray:
    """f0 frames (10 ms) for [(midi, seconds), ...]; midi <= 0 means rest."""
    rng = np.random.default_rng(seed)
    frames: list[np.ndarray] = [np.zeros(int(lead_s * 100))]
    for midi, dur in notes:
        k = int(round(dur * 100))
        if midi <= 0:
            frames.append(np.zeros(k))
            continue
        t = np.arange(k) / 100
        cents = np.full(k, float(detune_cents))
        if vibrato_hz:
            cents += vibrato_cents * np.sin(2 * np.pi * vibrato_hz * t)
        if scoop_cents:
            cents += scoop_cents * np.exp(-t / 0.05)
        if jitter_cents:
            walk = np.cumsum(rng.standard_normal(k)) * jitter_cents / 10
            cents += walk - np.mean(walk)
        frames.append(a4 * 2 ** ((midi - 69 + cents / 100) / 12))
        if gap_s:
            frames.append(np.zeros(int(gap_s * 100)))
    frames.append(np.zeros(int(tail_s * 100)))
    return np.concatenate(frames)
