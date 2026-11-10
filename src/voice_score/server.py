"""FastAPI app. Bind to 127.0.0.1 only: there is no auth."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

from . import __version__, trackers
from .service import BadRequest, analyze_bytes


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    trackers.get(trackers.DEFAULT)  # load the model before the first request
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="voice-score", version=__version__, lifespan=_lifespan)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__, "trackers": trackers.available(),
                "default_tracker": trackers.DEFAULT}

    # Sync handler on purpose: FastAPI runs it in its threadpool, so CPU-bound tracking
    # does not block /health.
    @app.post("/analyze")
    def analyze(audio: UploadFile = File(...), params: str = Form("{}")) -> JSONResponse:
        try:
            p = json.loads(params or "{}")
        except json.JSONDecodeError as exc:
            return JSONResponse({"error": f"params is not valid JSON: {exc}"}, status_code=400)
        try:
            return JSONResponse(analyze_bytes(audio.file.read(), p))
        except BadRequest as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)

    return app


app = create_app()
