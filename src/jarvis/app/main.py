"""FastAPI entrypoint for Layer 6."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from jarvis.app.api.v1.router import api_v1_router
from jarvis.app.dependencies import seed_default_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_default_user()
    yield


app = FastAPI(
    title="Newscope API",
    version="0.1.0",
    description="Thin Layer 6 API over Newscope ingestion, processing, retrieval, personalization and generation.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router)


@app.get("/favicon.ico", include_in_schema=False, response_model=None)
def favicon():
    favicon_path = Path(__file__).resolve().parents[3] / "web" / "public" / "favicon.svg"
    if favicon_path.exists():
        return FileResponse(favicon_path, media_type="image/svg+xml")
    return Response(status_code=204)
