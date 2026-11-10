from __future__ import annotations

import numpy as np
import pytest

from voice_score.rmvpe import decode, mel_filters


def test_mel_matches_librosa() -> None:
    librosa = pytest.importorskip("librosa")
    ref = librosa.filters.mel(sr=16000, n_fft=1024, n_mels=128, fmin=30, fmax=8000, htk=True)
    assert np.allclose(mel_filters(), ref, atol=1e-6)


def test_decode_peak_bin() -> None:
    sal = np.zeros((2, 360))
    sal[0, 100] = 1.0  # bin 100 -> 2000 + 1997.38 cents above 10 Hz
    f0, _ = decode(sal)
    assert f0[0] == pytest.approx(10 * 2 ** ((20 * 100 + 1997.3794084376191) / 1200))
    assert f0[1] == 0.0
