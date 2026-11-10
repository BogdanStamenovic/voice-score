from __future__ import annotations

import io

import numpy as np
import pytest
import soundfile as sf

from voice_score.synth import note_sequence, render


def wav_bytes(audio: np.ndarray, sr: int = 16000) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV")
    return buf.getvalue()


@pytest.fixture
def cde_vibrato() -> bytes:
    f = note_sequence([(60, 1.0), (62, 1.0), (64, 1.5)], gap_s=0.15, vibrato_hz=5.5,
                      vibrato_cents=40, detune_cents=-20)
    return wav_bytes(render(f, formants=False).audio)


@pytest.fixture
def a3_sharp() -> bytes:
    f = note_sequence([(57, 2.0)], detune_cents=30, scoop_cents=-150)
    return wav_bytes(render(f, noise_snr_db=25, formants=False).audio)
