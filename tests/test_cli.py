from __future__ import annotations

import json

import pytest

from voice_score.cli import main


def test_version(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "voice-score" in capsys.readouterr().out


def test_usage_error() -> None:
    assert main(["analyze"]) == 2


def test_analyze_file(tmp_path, a3_sharp: bytes, capsys) -> None:
    p = tmp_path / "a.wav"
    p.write_bytes(a3_sharp)
    assert main(["analyze", str(p), "--targets", "A3"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["notes"][0]["target_note"] == "A3"


def test_missing_file() -> None:
    assert main(["analyze", "/nonexistent.wav"]) == 1
