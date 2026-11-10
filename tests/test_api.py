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
