from __future__ import annotations

import numpy as np
import pytest

from voice_score.metrics import (
    MetricsError,
    Options,
    analyze,
    midi_to_note,
    note_to_midi,
    parse_targets,
    vibrato,
)
from voice_score.trackers import Contour


def contour(f0_frames: np.ndarray, hop: float = 0.01) -> Contour:
    f0 = np.where(f0_frames > 0, f0_frames, np.nan)
    return Contour(np.arange(len(f0)) * hop, f0, np.isfinite(f0).astype(float))


def tone(midi: float, secs: float, cents: float = 0.0) -> np.ndarray:
    return np.full(int(secs * 100), 440 * 2 ** ((midi - 69 + cents / 100) / 12))


def test_note_names() -> None:
    assert note_to_midi("C4") == 60
    assert note_to_midi("A4") == 69
    assert note_to_midi("Bb2") == 46
    assert note_to_midi("F#3") == 54
    assert midi_to_note(61) == "C#4"
    with pytest.raises(MetricsError):
        note_to_midi("H4")


def test_single_target_cents_error() -> None:
    c = contour(np.concatenate([np.zeros(30), tone(57, 2.0, cents=30), np.zeros(30)]))
    r = analyze(c, parse_targets([{"note": "A3"}]), Options())
    n = r["notes"][0]
    assert n["cents_error"] == pytest.approx(30, abs=0.5)
    assert n["pass"] is True
    assert n["sustain_s"] == pytest.approx(2.0, abs=0.05)
    assert n["stability_cents_sd"] < 1


def test_pass_threshold_and_octave() -> None:
    c = contour(np.concatenate([np.zeros(30), tone(48, 1.5, cents=-70), np.zeros(30)]))
    r = analyze(c, parse_targets(["C4"]), Options())
    n = r["notes"][0]
    assert n["octave_offset"] == -1
    assert n["cents_error"] == pytest.approx(-70, abs=0.5)
    assert n["pass"] is False
    r = analyze(c, parse_targets(["C4"]), Options(octave_agnostic=False))
    assert r["notes"][0]["cents_error"] == pytest.approx(-1270, abs=1)


def test_untimed_sequence_alignment() -> None:
    f = np.concatenate([np.zeros(20), tone(60, 0.8, 10), np.zeros(10), tone(64, 0.8, -15),
                        tone(67, 0.8, 5), np.zeros(20)])
    r = analyze(contour(f), parse_targets(["C4", "E4", "G4"]), Options())
    errs = [n["cents_error"] for n in r["notes"]]
    assert errs == pytest.approx([10, -15, 5], abs=2)


def test_missed_note_is_reported() -> None:
    f = np.concatenate([np.zeros(20), tone(60, 0.8), np.zeros(10), tone(67, 0.8), np.zeros(20)])
    r = analyze(contour(f), parse_targets(["C4", "E4", "G4"]), Options())
    assert r["notes"][1].get("missing") is True
    assert r["notes"][0]["pass"] and r["notes"][2]["pass"]


def test_beats_layout_from_first_onset() -> None:
    f = np.concatenate([np.zeros(50), tone(60, 0.5), tone(62, 0.5), tone(64, 1.0), np.zeros(20)])
    tg = parse_targets([{"note": "C4", "beats": 1}, {"note": "D4", "beats": 1},
                        {"note": "E4", "beats": 2}])
    r = analyze(contour(f), tg, Options(tempo_bpm=120))
    assert [n["start"] for n in r["notes"]] == pytest.approx([0.5, 1.0, 1.5], abs=0.02)
    assert all(n["pass"] for n in r["notes"])
    with pytest.raises(MetricsError):
        analyze(contour(f), tg, Options())


def test_rest_advances_time() -> None:
    f = np.concatenate([np.zeros(50), tone(60, 0.5), np.zeros(50), tone(64, 0.5), np.zeros(20)])
    tg = parse_targets([{"note": "C4", "beats": 1}, {"rest": True, "beats": 1},
                        {"note": "E4", "beats": 1}])
    r = analyze(contour(f), tg, Options(tempo_bpm=120))
    assert [n["target_note"] for n in r["notes"]] == ["C4", "E4"]
    assert all(n["pass"] for n in r["notes"])


def test_vibrato_rate_and_extent() -> None:
    t = np.arange(300) / 100
    cents = 50 * np.sin(2 * np.pi * 6.0 * t)
    v = vibrato(cents, 0.01)
    assert v["present"]
    assert v["rate_hz"] == pytest.approx(6.0, abs=0.15)
    assert v["extent_cents"] == pytest.approx(50, rel=0.15)
    flat = vibrato(np.random.default_rng(0).normal(0, 3, 300), 0.01)
    assert not flat["present"]


def test_vibrato_excluded_from_stability() -> None:
    t = np.arange(200) / 100
    f = 220 * 2 ** (40 * np.sin(2 * np.pi * 5.5 * t) / 1200)
    r = analyze(contour(np.concatenate([np.zeros(20), f, np.zeros(20)])),
                parse_targets(["A3"]), Options())
    n = r["notes"][0]
    assert n["raw_cents_sd"] > 20
    assert n["stability_cents_sd"] < 8
    assert n["sustain_s"] > 1.9


def test_free_singing_range() -> None:
    f = np.concatenate([np.zeros(20), tone(45, 0.6), tone(52, 0.6), tone(64, 0.6), np.zeros(20)])
    r = analyze(contour(f), [], Options())
    rg = r["summary"]["range"]
    assert rg["low_note"] == "A2" and rg["high_note"] == "E4"
    assert len(r["notes"]) == 3


def test_nothing_voiced() -> None:
    from voice_score.metrics import NothingVoiced

    with pytest.raises(NothingVoiced):
        analyze(contour(np.zeros(200)), [], Options())


def test_short_beats_fast_tempo() -> None:
    # 16th notes at 200 bpm = 75 ms windows, shorter than the 0.25 s smoothing kernel
    seq = [tone(60 + 2 * (i % 2), 0.075) for i in range(8)]
    f = np.concatenate([np.zeros(20), *seq, np.zeros(20)])
    tg = parse_targets([{"midi": 60 + 2 * (i % 2), "beats": 0.25} for i in range(8)])
    r = analyze(contour(f), tg, Options(tempo_bpm=200))
    assert len(r["notes"]) == 8
