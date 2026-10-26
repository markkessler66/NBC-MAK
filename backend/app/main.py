"""Personal Weather Lab — FastAPI application entrypoint.

Run from the backend/ directory:
    uvicorn app.main:app --host 127.0.0.1 --port 8000
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import settings
from .db import init_db
from .http_client import close_client
from .ingest.nws import resolve_point
from .scheduler import start_jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("weatherlab")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        point = await resolve_point()
        log.info("NWS gridpoint resolved: %s %s,%s (stations: %s)",
                 point["grid_id"], point["grid_x"], point["grid_y"], ", ".join(point["stations"][:3]))
    except Exception as exc:
        log.warning("Could not resolve NWS point at startup (will retry via jobs): %s", exc)
    tasks = start_jobs()
    log.info("Started %d ingestion loops for %s", len(tasks), settings.home_name)
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await close_client()


app = FastAPI(title="Personal Weather Lab", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# Serve the built frontend (frontend/dist) if present, so a single uvicorn
# process can host the whole app in "production" mode.
_dist = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
