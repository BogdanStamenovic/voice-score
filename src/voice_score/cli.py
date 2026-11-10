"""Command-line interface for voice-score.

stdout carries only real output (JSON from `analyze`); progress, warnings and
errors go to stderr.
Exit codes: 0 success, 1 analysis failed (bad audio, nothing voiced), 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from typing import NoReturn

from . import __version__

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3311


class _UsageError(Exception):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _UsageError(message)


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="voice-score", description="Analyze singing recordings.")
    parser.add_argument("-v", "--verbose", action="store_true", help="print detailed progress")
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress non-error output")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True, parser_class=_ArgumentParser)

    s = sub.add_parser("serve", help="run the HTTP API")
    s.add_argument("--host", default=os.environ.get("VOICE_SCORE_HOST", DEFAULT_HOST))
    s.add_argument("--port", type=int, default=int(os.environ.get("VOICE_SCORE_PORT", DEFAULT_PORT)))

    a = sub.add_parser("analyze", help="analyze one file and print the JSON response")
    a.add_argument("file")
    a.add_argument("--targets", help="comma-separated notes, e.g. C4,D4,E4 (or 60,62,64)")
    a.add_argument("--beats", help="comma-separated beats per target (needs --tempo)")
    a.add_argument("--tempo", type=float, help="tempo in BPM")
    a.add_argument("--tracker", help="pitch tracker (default swiftf0)")
    a.add_argument("--params", help="raw params JSON (overrides the flags above)")
    a.add_argument("--contour", action="store_true", help="include the f0 contour")

    sub.add_parser("trackers", help="list installed trackers")

    b = sub.add_parser("bench", help="benchmark trackers head-to-head (needs the bench extra)")
    b.add_argument("--trackers", default="swiftf0,pyin,fcpe,pesto,rmvpe")
    b.add_argument("--datasets", default="synth,vocadito")
    b.add_argument("--out", help="directory for results.json / results.csv / results.md")
    return parser


def _params(args: argparse.Namespace) -> dict:
    if args.params:
        return json.loads(args.params)
    p: dict = {"contour": args.contour}
    if args.targets:
        names = [x.strip() for x in args.targets.split(",") if x.strip()]
        tg: list[dict] = [{"midi": int(n)} if n.lstrip("-").isdigit() else {"note": n}
                          for n in names]
        if args.beats:
            beats = [float(b) for b in args.beats.split(",")]
            if len(beats) != len(tg):
                raise _UsageError("--beats needs one value per target")
            for t, b in zip(tg, beats):
                t["beats"] = b
        p["targets"] = tg
    if args.tempo:
        p["tempo_bpm"] = args.tempo
    if args.tracker:
        p["tracker"] = args.tracker
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        if args.cmd == "analyze":
            params = _params(args)
    except (_UsageError, json.JSONDecodeError, ValueError) as exc:
        print(f"voice-score: error: {exc}", file=sys.stderr)
        return 2

    if args.cmd == "serve":
        import uvicorn

        if not args.quiet:
            print(f"voice-score {__version__} on http://{args.host}:{args.port}", file=sys.stderr)
        uvicorn.run("voice_score.server:app", host=args.host, port=args.port,
                    log_level="info" if args.verbose else "warning")
        return 0

    if args.cmd == "trackers":
        from . import trackers

        for name in trackers.available():
            print(name + (" (default)" if name == trackers.DEFAULT else ""))
        return 0

    if args.cmd == "bench":
        from pathlib import Path

        from . import bench

        out = Path(args.out) if args.out else None
        if out:
            out.mkdir(parents=True, exist_ok=True)
        res = bench.run(args.trackers.split(","), args.datasets.split(","),
                        out / "results.json" if out else None)
        md = bench.markdown(res)
        if out:
            (out / "results.md").write_text(md + "\n")
            bench.write_csv(res, out / "results.csv")
        print(md)
        return 0

    from .service import BadRequest, analyze_bytes

    try:
        with open(args.file, "rb") as fh:
            result = analyze_bytes(fh.read(), params)
    except OSError as exc:
        print(f"voice-score: error: {exc}", file=sys.stderr)
        return 1
    except BadRequest as exc:
        print(f"voice-score: error: {exc}", file=sys.stderr)
        return 1
    for w in result.get("warnings", []):
        if not args.quiet:
            print(f"voice-score: warning: {w}", file=sys.stderr)
    print(json.dumps(result, indent=2))
    return 0
