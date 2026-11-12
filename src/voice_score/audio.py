"""Decode uploaded audio into mono float32 samples."""

from __future__ import annotations

import io
import shutil
import subprocess
from dataclasses import dataclass

import numpy as np

MAX_SECONDS = 60.0
MAX_BYTES = 20 * 1024 * 1024
FFMPEG_RATE = 16000


class AudioError(Exception):
    """Audio could not be decoded or violates a limit. `status` is the HTTP code to use."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Audio:
    samples: np.ndarray  # mono float32 in [-1, 1]
    sample_rate: int

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate


def _to_mono(data: np.ndarray) -> np.ndarray:
    if data.ndim == 2:
        data = data.mean(axis=1)
    return np.ascontiguousarray(data, dtype=np.float32)


def _decode_soundfile(blob: bytes) -> Audio | None:
    import soundfile as sf

    try:
        data, rate = sf.read(io.BytesIO(blob), dtype="float32", always_2d=False)
    except Exception:
        return None
    return Audio(_to_mono(np.asarray(data)), int(rate))


def _decode_ffmpeg(blob: bytes) -> Audio:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise AudioError("unsupported audio format (only WAV/FLAC/OGG without ffmpeg installed)")
    # webm/mp4 containers from MediaRecorder are not always seekable from a pipe, but ffmpeg
    # handles both from stdin; -t caps decode work for oversized uploads.
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-t", str(MAX_SECONDS + 1),
         "-f", "f32le", "-ac", "1", "-ar", str(FFMPEG_RATE), "pipe:1"],
        input=blob, capture_output=True, timeout=60, check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        msg = proc.stderr.decode(errors="replace").strip().splitlines()
        raise AudioError(f"could not decode audio: {msg[-1] if msg else 'ffmpeg failed'}")
    return Audio(np.frombuffer(proc.stdout, dtype=np.float32).copy(), FFMPEG_RATE)


def decode(blob: bytes) -> Audio:
    if len(blob) > MAX_BYTES:
        raise AudioError(f"audio larger than {MAX_BYTES // (1024 * 1024)} MB", status=413)
    if not blob:
        raise AudioError("empty audio upload")
    audio = _decode_soundfile(blob) or _decode_ffmpeg(blob)
    if audio.duration > MAX_SECONDS:
        raise AudioError(f"audio longer than {MAX_SECONDS:.0f} s", status=413)
    if audio.duration < 0.05:
        raise AudioError("audio shorter than 50 ms")
    return audio


def read_file(path: str) -> Audio:
    with open(path, "rb") as fh:
        return decode(fh.read())


# SwiftF0 treats frames whose peak is below 1e-3 (-60 dBFS) as digital silence. Measured on
# Bogdan's own takes (2026-11-12): his voiced frames peak at -37.5 dBFS (median), and turning
# the takes down showed notes shifting from -5 dB and "no voice detected" from -20 dB. So the
# useful warning is the margin to that gate, not the whole-file RMS (which counts silence).
LOW_LEVEL_PEAK_DB = -45.0  # median voiced frame peak; 15 dB above the gate
NOISY_SNR_DB = 6.0  # voiced energy over the take's own background (median unvoiced energy)


def level_warnings(audio: Audio, t: np.ndarray | None = None,
                   voiced: np.ndarray | None = None, hop: float = 0.016) -> list[str]:
    """Clipping, low level and noise warnings. Level and noise need the tracker's voicing."""
    x = audio.samples
    warnings: list[str] = []
    if x.size == 0:
        return warnings
    clipped = float(np.mean(np.abs(x) >= 0.999))
    if clipped > 0.001:
        warnings.append(f"clipping: {clipped:.1%} of samples at full scale; move back from the mic")
    if t is None or voiced is None or not voiced.any():
        return warnings
    sr = audio.sample_rate
    w = max(1, int(round(hop * sr)))
    starts = np.clip((np.asarray(t) * sr).astype(int), 0, max(0, len(x) - 1))
    frames = [x[i:i + w].astype(np.float64) for i in starts]
    peak = np.array([np.abs(f).max() if f.size else 0.0 for f in frames])
    energy = np.array([np.mean(f ** 2) if f.size else 0.0 for f in frames])
    peak_db = 20 * np.log10(max(float(np.median(peak[voiced])), 1e-9))
    if peak_db < LOW_LEVEL_PEAK_DB:
        warnings.append(f"low recording level (voice peaks at {peak_db:.0f} dBFS); quieter singing "
                        "may be missed: raise the mic gain or move closer")
    if (~voiced).sum() >= 10:
        noise = float(np.median(energy[~voiced]))
        if noise > 0:
            snr = 10 * np.log10(max(float(np.mean(energy[voiced])), 1e-20) / noise)
            if snr < NOISY_SNR_DB:
                warnings.append(f"noisy recording: voice only {snr:.0f} dB above the background; "
                                "pitch may be less reliable")
    return warnings
