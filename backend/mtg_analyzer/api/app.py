"""FastAPI application — a thin adapter over the engine.

Phase 0: health route + CORS for local dev. Feature routes are added per the
phases in project-plan.md (card lookup, deck import/analysis, recommendations).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mtg_analyzer import __version__

# Vite dev server origins (local single-user dev). Tighten/remove for any future hosting.
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app = FastAPI(
    title="MTG Analyzer",
    version=__version__,
    summary="Local Commander (EDH) deck analyzer, simulator, and recommender.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by the frontend to confirm the backend is up."""
    return {"status": "ok", "version": __version__}
