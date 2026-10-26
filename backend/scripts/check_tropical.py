"""Smoke-check the tropical endpoints against live NHC/GFS data.

Runs the FastAPI app in-process (no server needed):
    python scripts/check_tropical.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.ingest import nhc
from app.main import app
from app.state import LATEST

logging.disable(logging.INFO)
RULE = "=" * 78


def show_metrics(metrics: list[dict]) -> None:
    for m in metrics:
        cat = m.get("category") or ""
        print(f"    {m['label']:<30} {m['display']:<34} {cat} [{m['tone']}]")


async def main() -> int:
    LATEST.tropical = await nhc.fetch_tropical()
    storms = LATEST.tropical["storms"]
    print(f"active systems: {len(storms)}")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/tropical")
        print(f"GET /api/tropical -> {resp.status_code} ({len(resp.content)} bytes)")

        for storm in storms:
            sid = storm["id"]
            resp = await client.get(f"/api/tropical/{sid}")
            print(RULE)
            print(f"{sid} {storm['name']} -> {resp.status_code} ({len(resp.content)} bytes)")
            if resp.status_code != 200:
                print(resp.text[:400])
                continue

            detail = resp.json()
            diag = detail["diagnostics"]
            cone = storm.get("cone") or {}
            track = storm.get("track") or {}

            print(f"cone rings: {len(cone.get('features') or [])}"
                  f" | track points: {len(track.get('points') or [])}"
                  f" | along-track stops: {len(detail['environment']['along_track'])}")
            print()
            print("HEADLINE:", diag["headline"])
            print()
            print(f"INTENSITY  score={diag['intensity']['score']}  {diag['intensity']['verdict']}")
            print(" ", diag["intensity"]["narrative"])
            show_metrics(diag["intensity"]["metrics"])
            print()
            steering = diag["steering"]
            print(f"STEERING   ref={steering['reference_layer']}"
                  f"  motion-vs-flow={steering['agreement_deg']}°")
            print(" ", diag["steering"]["narrative"])
            show_metrics(diag["steering"]["metrics"])
            print()
            advisory = detail.get("advisory") or {}
            wind = detail.get("wind_field") or {}
            print(f"wind size class: {wind.get('size_class')}"
                  f" | radii: {sorted((wind.get('radii') or {}).keys())}")
            print(f"seas: {advisory.get('seas_nm')}")
            print(f"advisory text: {'yes' if advisory.get('text') else 'no'}"
                  f" | discussion: {'yes' if detail.get('discussion') else 'no'}")

        resp = await client.get("/api/tropical/zz99")
        print(RULE)
        print(f"unknown id -> {resp.status_code} (expected 404)")
        return 0 if resp.status_code == 404 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
