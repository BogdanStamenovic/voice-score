"""Request-level glue: audio bytes + params -> response dict. Shared by HTTP and CLI."""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from . import __version__, trackers
from .audio import Audio, AudioError, decode, level_warnings
from .metrics import MetricsError, NothingVoiced, Options, analyze, parse_targets

KNOWN_PARAMS = {"targets", "tempo_bpm", "a4_hz", "tracker", "contour", "pass_cents",
                "octave_agnostic"}


class BadRequest(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _opt(params: dict[str, Any]) -> Options:
    try:
        o = Options(
            a4_hz=float(params.get("a4_hz", 440.0)),
            pass_cents=float(params.get("pass_cents", 50.0)),
            octave_agnostic=bool(params.get("octave_agnostic", True)),
            tempo_bpm=float(params["tempo_bpm"]) if params.get("tempo_bpm") else None,
        )
    except (TypeError, ValueError) as exc:
        raise BadRequest(f"bad numeric parameter: {exc}") from exc
    if not 380 <= o.a4_hz <= 500:
        raise BadRequest("a4_hz must be within 380-500")
    if o.pass_cents <= 0:
        raise BadRequest("pass_cents must be positive")
    if o.tempo_bpm is not None and not 10 <= o.tempo_bpm <= 400:
        raise BadRequest("tempo_bpm must be within 10-400")
    return o


def analyze_audio(audio: Audio, params: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise BadRequest("params must be a JSON object")
    unknown = set(params) - KNOWN_PARAMS
    opt = _opt(params)
    name = str(params.get("tracker") or trackers.DEFAULT)
    try:
        tracker = trackers.get(name)
    except trackers.TrackerUnavailable as exc:
        raise BadRequest(str(exc)) from exc
    try:
        targets = parse_targets(list(params.get("targets") or []))
    except (MetricsError, TypeError, ValueError) as exc:
        raise BadRequest(str(exc)) from exc
    t0 = time.perf_counter()
    contour = tracker.track(audio.samples, audio.sample_rate)
    elapsed = time.perf_counter() - t0
    try:
        result = analyze(contour, targets, opt)
    except NothingVoiced as exc:
        raise BadRequest(str(exc), status=422) from exc
    except MetricsError as exc:
        raise BadRequest(str(exc)) from exc
    warnings = level_warnings(audio) + result.pop("warnings")
    if unknown:
        warnings.append(f"ignored unknown params: {', '.join(sorted(unknown))}")
    resp: dict[str, Any] = {
        "version": __version__,
        "tracker": name,
        "a4_hz": opt.a4_hz,
        "pass_cents": opt.pass_cents,
        "octave_agnostic": opt.octave_agnostic,
        "tempo_bpm": opt.tempo_bpm,
        "duration_s": round(audio.duration, 3),
        "hop_s": round(contour.hop, 5),
        "tracker_ms": round(elapsed * 1000, 1),
        **result,
        "labels": {},
        "warnings": warnings,
    }
    if params.get("contour", True):
        resp["contour"] = {
            "t": [round(float(x), 4) for x in contour.t],
            "f0_hz": [None if not np.isfinite(x) else round(float(x), 2) for x in contour.f0],
            "confidence": [round(float(x), 3) for x in contour.confidence],
        }
    return resp


def analyze_bytes(blob: bytes, params: dict[str, Any]) -> dict[str, Any]:
    try:
        audio = decode(blob)
    except AudioError as exc:
        raise BadRequest(str(exc), exc.status) from exc
    return analyze_audio(audio, params)
