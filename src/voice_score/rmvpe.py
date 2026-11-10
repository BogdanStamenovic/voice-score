"""RMVPE pitch tracker via its ONNX export, on onnxruntime (no torch).

Weights: rmvpe.onnx (362 MB, MIT) from huggingface.co/lj1995/VoiceConversionWebUI.
Pre/post-processing is a numpy port of RVC's infer/lib/rmvpe.py (MIT): a 128-band
HTK mel spectrogram (n_fft 1024, hop 160 at 16 kHz, 30-8000 Hz, log clamp 1e-5),
the model output (360 salience bins, 20 cents apart), and a local weighted
average of 9 bins around the argmax. Frames whose peak salience is <= 0.03 are
unvoiced, as in RVC.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import numpy as np

SR = 16000
N_FFT = 1024
HOP = 160
N_MELS = 128
THRESHOLD = 0.03


def model_path() -> Path:
    env = os.environ.get("VOICE_SCORE_RMVPE")
    if env:
        return Path(env)
    for base in (Path("/mnt/windows/voice-score-data/models"),
                 Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "voice-score/models"):
        if (base / "rmvpe.onnx").exists():
            return base / "rmvpe.onnx"
    raise ImportError("rmvpe.onnx not found; set VOICE_SCORE_RMVPE or run scripts/fetch-models.sh")


def _hz_to_mel(f: np.ndarray) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + f / 700.0)


def _mel_to_hz(m: np.ndarray) -> np.ndarray:
    return 700.0 * (10.0 ** (m / 2595.0) - 1.0)


def mel_filters(sr: int = SR, n_fft: int = N_FFT, n_mels: int = N_MELS,
                fmin: float = 30.0, fmax: float = 8000.0) -> np.ndarray:
    """Equivalent of librosa.filters.mel(htk=True, norm='slaney')."""
    fftfreqs = np.linspace(0, sr / 2, 1 + n_fft // 2)
    mel_f = _mel_to_hz(np.linspace(_hz_to_mel(np.array(fmin)), _hz_to_mel(np.array(fmax)), n_mels + 2))
    fdiff = np.diff(mel_f)
    ramps = np.subtract.outer(mel_f, fftfreqs)
    weights = np.zeros((n_mels, len(fftfreqs)))
    for i in range(n_mels):
        lower = -ramps[i] / fdiff[i]
        upper = ramps[i + 2] / fdiff[i + 1]
        weights[i] = np.maximum(0, np.minimum(lower, upper))
    weights *= (2.0 / (mel_f[2: n_mels + 2] - mel_f[:n_mels]))[:, None]
    return weights.astype(np.float32)


def log_mel(audio: np.ndarray, basis: np.ndarray) -> np.ndarray:
    pad = N_FFT // 2
    x = np.pad(audio.astype(np.float32), (pad, pad), mode="reflect")
    n_frames = 1 + (len(x) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    window = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N_FFT) / N_FFT)).astype(np.float32)
    mag = np.abs(np.fft.rfft(x[idx] * window, axis=1)).T  # (bins, frames)
    return np.log(np.maximum(basis @ mag, 1e-5)).astype(np.float32)


_CENTS = np.pad(20 * np.arange(360) + 1997.3794084376191, (4, 4))


def decode(salience: np.ndarray, threshold: float = THRESHOLD) -> tuple[np.ndarray, np.ndarray]:
    center = np.argmax(salience, axis=1) + 4
    padded = np.pad(salience, ((0, 0), (4, 4)))
    offs = center[:, None] + np.arange(-4, 5)[None, :]
    rows = np.arange(len(salience))[:, None]
    sal = padded[rows, offs]
    cents = (sal * _CENTS[offs]).sum(1) / np.maximum(sal.sum(1), 1e-9)
    peak = salience.max(axis=1)
    f0 = 10 * 2 ** (cents / 1200)
    f0[peak <= threshold] = 0.0
    return f0, peak


def load_rmvpe(path: Path | None = None) -> Callable[[np.ndarray], tuple[np.ndarray, ...]]:
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 4
    sess = ort.InferenceSession(str(path or model_path()), opts, providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    out_name = sess.get_outputs()[0].name
    basis = mel_filters()

    def run(audio16k: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        mel = log_mel(audio16k, basis)[None]  # (1, 128, T)
        n = mel.shape[-1]
        n_pad = 32 * ((n - 1) // 32 + 1) - n
        if n_pad:
            mel = np.pad(mel, ((0, 0), (0, 0), (0, n_pad)))
        hidden = sess.run([out_name], {in_name: mel})[0]
        hidden = np.asarray(hidden).reshape(-1, hidden.shape[-1])[:n]
        f0, peak = decode(hidden, threshold=-1.0)  # raw pitch everywhere; caller thresholds
        return np.arange(n) * HOP / SR, f0, peak

    return run
