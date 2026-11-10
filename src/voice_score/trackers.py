"""Pitch trackers behind one interface.

SwiftF0 is the only tracker in the default install. The others exist for the
benchmark (and can be selected per request when their extra is installed); each
imports its heavy dependency lazily so a missing extra only removes that tracker.
"""

from __future__ import annotations

import contextlib
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

FMIN = 50.0
FMAX = 2000.0
THRESHOLD_RMVPE = 0.03  # RVC default


@dataclass
class Contour:
    t: np.ndarray  # frame times, seconds
    f0: np.ndarray  # Hz, NaN where unvoiced
    confidence: np.ndarray  # tracker-specific voicing score; voiced = confidence >= threshold
    raw_f0: np.ndarray | None = None  # best pitch guess for every frame (for threshold sweeps)
    threshold: float = 0.5

    @property
    def hop(self) -> float:
        return float(np.median(np.diff(self.t))) if len(self.t) > 1 else 0.0

    @property
    def voiced(self) -> np.ndarray:
        return np.isfinite(self.f0)


class TrackerUnavailable(Exception):
    pass


def _resample(x: np.ndarray, sr: int, target: int) -> np.ndarray:
    if sr == target:
        return x.astype(np.float32, copy=False)
    import soxr

    return np.asarray(soxr.resample(x, sr, target), dtype=np.float32)


class SwiftF0Tracker:
    name = "swiftf0"

    def __init__(self) -> None:
        from swift_f0 import SwiftF0

        # spin=False: this runs inside a shared server; busy-waiting threads would burn
        # CPU between requests (swift-f0 docstring: costs ~1 ms per call).
        self._det = SwiftF0(threads=4, spin=False)

    def track(self, x: np.ndarray, sr: int) -> Contour:
        r = self._det.detect(x, sr, fmin=FMIN, fmax=FMAX)
        f0 = np.where(r.confidence >= 0.5, r.pitch_hz, np.nan)
        return Contour(r.timestamps, f0, r.confidence, r.pitch_hz, 0.5)


class PyinTracker:
    name = "pyin"

    def __init__(self) -> None:
        import librosa  # noqa: F401

    def track(self, x: np.ndarray, sr: int) -> Contour:
        import librosa

        y = _resample(x, sr, 16000)
        hop = 256
        raw, flag, prob = librosa.pyin(y, fmin=FMIN, fmax=FMAX, sr=16000, frame_length=2048,
                                       hop_length=hop, center=True, fill_na=None)
        t = np.arange(len(raw)) * hop / 16000
        # pYIN's voicing comes from its HMM (flag), not from thresholding prob; the default
        # contour keeps that decision, the sweep thresholds prob instead.
        f0 = np.where(flag, raw, np.nan)
        return Contour(t, f0, np.nan_to_num(prob), raw, 0.5)


class FcpeTracker:
    name = "fcpe"
    sweep = False  # the benchmark sets this to get a confidence; 12x slower
    GRID = (0.006, 0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)

    def __init__(self) -> None:
        import torch
        from torchfcpe import spawn_bundled_infer_model

        self._torch = torch
        # torchfcpe prints its config to stdout, which would corrupt the CLI's JSON output
        with contextlib.redirect_stdout(sys.stderr):
            self._model = spawn_bundled_infer_model(device="cpu")

    def track(self, x: np.ndarray, sr: int) -> Contour:
        torch = self._torch
        y = _resample(x, sr, 16000)
        hop = 160
        n = len(y) // hop + 1
        # FCPE exposes no confidence, only a mask threshold on its salience peak. Run it at a
        # grid of thresholds; a frame's confidence is the highest threshold it survives.
        # Default contour = FCPE's own default threshold (0.006).
        raw = np.zeros(n)
        conf = np.zeros(n)
        f0_default: np.ndarray | None = None
        with torch.no_grad():
            for th in self.GRID if self.sweep else self.GRID[:1]:
                f0 = self._model.infer(torch.from_numpy(y)[None, :, None], sr=16000,
                                       decoder_mode="local_argmax", threshold=th,
                                       f0_min=FMIN, f0_max=FMAX, interp_uv=False,
                                       output_interp_target_length=n)
                f0 = f0.squeeze().cpu().numpy().astype(np.float64)
                if f0_default is None:
                    f0_default = f0
                    raw = f0.copy()
                conf[f0 > 0] = th
        assert f0_default is not None
        return Contour(np.arange(n) * hop / 16000, np.where(f0_default > 0, f0_default, np.nan),
                       conf, np.where(raw > 0, raw, np.nan), self.GRID[0])


class PestoTracker:
    name = "pesto"

    def __init__(self) -> None:
        import pesto
        import torch

        self._pesto = pesto
        self._torch = torch

    def track(self, x: np.ndarray, sr: int) -> Contour:
        torch = self._torch
        y = _resample(x, sr, 16000)
        with torch.no_grad():
            t, f0, conf, _ = self._pesto.predict(torch.from_numpy(y), 16000, step_size=10.0,
                                                 convert_to_freq=True)
        t = t.cpu().numpy().astype(np.float64)
        if t.max(initial=0) > len(y) / 16000 * 10:  # older pesto returns ms
            t = t / 1000.0
        f0 = f0.cpu().numpy().astype(np.float64)
        conf = conf.cpu().numpy().astype(np.float64)
        # PESTO has no voicing decision; 0.5 on its confidence is the convention its
        # README uses for display. Benchmarked as-is.
        return Contour(t, np.where(conf >= 0.5, f0, np.nan), conf, f0, 0.5)


class RmvpeTracker:
    name = "rmvpe"

    def __init__(self) -> None:
        from .rmvpe import load_rmvpe

        self._model = load_rmvpe()

    def track(self, x: np.ndarray, sr: int) -> Contour:
        y = _resample(x, sr, 16000)
        t, raw, conf = self._model(y)
        f0 = np.where(conf > THRESHOLD_RMVPE, raw, np.nan)
        return Contour(t, f0, conf, raw, THRESHOLD_RMVPE)


FACTORIES: dict[str, Callable[[], object]] = {
    "swiftf0": SwiftF0Tracker,
    "pyin": PyinTracker,
    "fcpe": FcpeTracker,
    "pesto": PestoTracker,
    "rmvpe": RmvpeTracker,
}
DEFAULT = "swiftf0"

_cache: dict[str, object] = {}
_lock = threading.Lock()


def get(name: str) -> SwiftF0Tracker:
    """Return a cached tracker instance. Raises TrackerUnavailable if its extra is missing."""
    if name not in FACTORIES:
        raise TrackerUnavailable(f"unknown tracker {name!r}; known: {', '.join(FACTORIES)}")
    with _lock:
        if name not in _cache:
            try:
                _cache[name] = FACTORIES[name]()
            except ImportError as exc:
                raise TrackerUnavailable(f"tracker {name!r} not installed ({exc})") from exc
        return _cache[name]  # type: ignore[return-value]


def available() -> list[str]:
    import importlib.util

    from .rmvpe import model_path

    probes = {"swiftf0": "swift_f0", "pyin": "librosa", "fcpe": "torchfcpe", "pesto": "pesto"}
    names = [n for n, mod in probes.items() if importlib.util.find_spec(mod) is not None]
    try:
        if model_path().exists():
            names.append("rmvpe")
    except ImportError:
        pass
    return names
