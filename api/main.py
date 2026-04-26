"""
pt-media-os — FastAPI Internal API

Serves event data, outlet profiles, digest, search, and provenance endpoints
for the public Next.js frontend.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from api.routes import events, outlets, digest, undercoverage, search
from db.pool import close_pool

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    logger.info("PT Media OS API starting up")
    yield
    await close_pool()
    logger.info("PT Media OS API shutting down")


app = FastAPI(
    title="PT Media OS — Internal API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include route modules
app.include_router(events.router, prefix="/api", tags=["events"])
app.include_router(outlets.router, prefix="/api", tags=["outlets"])
app.include_router(digest.router, prefix="/api", tags=["digest"])
app.include_router(undercoverage.router, prefix="/api", tags=["undercoverage"])
app.include_router(search.router, prefix="/api", tags=["search"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
