from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from voice_score import __version__
from voice_score.server import create_app

from .conftest import wav_bytes


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(create_app()) as c:
        yield c


def post(client: TestClient, audio: bytes, params: dict | str | None = None):
    data = {} if params is None else {"params": params if isinstance(params, str) else json.dumps(params)}
    return client.post("/analyze", files={"audio": ("a.wav", audio, "audio/wav")}, data=data)


def test_health(client: TestClient) -> None:
    r = client.get("/health").json()
    assert r["ok"] and r["version"] == __version__ and "swiftf0" in r["trackers"]


def test_analyze_sequence(client: TestClient, cde_vibrato: bytes) -> None:
    r = post(client, cde_vibrato, {"targets": ["C4", "D4", "E4"], "a4_hz": 440})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["version"] == __version__ and d["a4_hz"] == 440 and d["pass_cents"] == 50
    assert [n["target_note"] for n in d["notes"]] == ["C4", "D4", "E4"]
    for n in d["notes"]:
        assert n["cents_error"] == pytest.approx(-20, abs=12)
        assert n["vibrato"]["present"]
        assert n["vibrato"]["rate_hz"] == pytest.approx(5.5, abs=0.3)
    assert len(d["contour"]["t"]) == len(d["contour"]["f0_hz"])


def test_single_target(client: TestClient, a3_sharp: bytes) -> None:
    d = post(client, a3_sharp, {"targets": [{"note": "A3"}], "contour": False}).json()
    assert "contour" not in d
    n = d["notes"][0]
    assert n["cents_error"] == pytest.approx(30, abs=8)
    assert n["sustain_s"] > 1.7


def test_silence_is_422(client: TestClient) -> None:
    r = post(client, wav_bytes(np.zeros(16000, dtype=np.float32)))
    assert r.status_code == 422


def test_bad_inputs(client: TestClient, a3_sharp: bytes) -> None:
    assert post(client, b"not audio at all").status_code == 400
    assert post(client, a3_sharp, "{nope").status_code == 400
    assert post(client, a3_sharp, {"targets": ["H9"]}).status_code == 400
    assert post(client, a3_sharp, {"tracker": "nope"}).status_code == 400
    r = post(client, a3_sharp, {"targets": [{"note": "A3", "beats": 2}]})
    assert r.status_code == 400 and "tempo_bpm" in r.json()["error"]


def test_too_long_is_413(client: TestClient) -> None:
    r = post(client, wav_bytes(np.zeros(16000 * 61, dtype=np.float32)))
    assert r.status_code == 413


def test_webm_via_ffmpeg(client: TestClient, a3_sharp: bytes, tmp_path) -> None:
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    src = tmp_path / "a.wav"
    src.write_bytes(a3_sharp)
    dst = tmp_path / "a.webm"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(src), "-c:a", "libopus",
                    str(dst)], check=True)
    d = post(client, dst.read_bytes(), {"targets": ["A3"]}).json()
    assert d["notes"][0]["cents_error"] == pytest.approx(30, abs=10)


def _take(level: float, noise_db: float | None = None) -> bytes:
    from voice_score.synth import note_sequence, render

    f = note_sequence([(50, 2.0)], lead_s=0.6, tail_s=0.6)
    x = render(f, formants=False).audio.astype(np.float64)
    x *= level / np.abs(x).max()
    if noise_db is not None:  # background noise noise_db below the voice, everywhere
        rng = np.random.default_rng(0)
        v = np.abs(x) > 0
        x = x + rng.standard_normal(len(x)) * np.sqrt(np.mean(x[v] ** 2) / 10 ** (noise_db / 10))
    return wav_bytes(x.astype(np.float32))


def test_level_warnings(client: TestClient) -> None:
    def warns(audio: bytes) -> list[str]:
        r = post(client, audio, {"targets": ["D3"], "contour": False})
        assert r.status_code == 200, r.text
        return [w.split(" ")[0] + " " + w.split(" ")[1] for w in r.json()["warnings"]]

    assert warns(_take(0.3)) == []
    assert warns(_take(0.003)) == ["low recording"]  # peaks at -50 dBFS, 10 dB above the gate
    assert warns(_take(0.3, noise_db=3)) == ["noisy recording:"]
    assert warns(_take(0.3, noise_db=20)) == []


def test_warning_prefixes_are_stable(client: TestClient) -> None:
    # music-trainer matches these two prefixes to show the warning to the singer (2026-11-12).
    # Rewording the rest of the message is fine; changing the prefix breaks the app.
    quiet = post(client, _take(0.003), {"targets": ["D3"]}).json()["warnings"]
    noisy = post(client, _take(0.3, noise_db=3), {"targets": ["D3"]}).json()["warnings"]
    assert any(w.startswith("low recording level") for w in quiet)
    assert any(w.startswith("noisy recording") for w in noisy)
