"""Smoke-check the gridded environment endpoint against live data."""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.ingest import nhc
from app.main import app
from app.state import LATEST

logging.disable(logging.INFO)


def summarise(name: str, grid: list[list[float | None]]) -> str:
    flat = [v for row in grid for v in row if v is not None]
    if not flat:
        return f"{name:<20} all null"
    missing = sum(1 for row in grid for v in row if v is None)
    return (f"{name:<20} min={min(flat):>8.1f}  max={max(flat):>8.1f}  "
            f"mean={sum(flat) / len(flat):>8.1f}  null={missing}")


async def main() -> int:
    LATEST.tropical = await nhc.fetch_tropical()
    storms = LATEST.tropical["storms"]
    if not storms:
        print("no active storms")
        return 0

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        sid = storms[0]["id"]
        for hour in (0, 48):
            started = time.time()
            resp = await client.get(f"/api/tropical/{sid}/fields",
                                    params={"hour": hour}, timeout=180)
            elapsed = time.time() - started
            print("=" * 70)
            print(f"{sid} hour={hour} -> {resp.status_code} "
                  f"({len(resp.content)} bytes, {elapsed:.1f}s)")
            if resp.status_code != 200:
                print(resp.text[:400])
                continue
            data = resp.json()
            print(f"valid {data['valid_time']}  centre {data['centre']}  "
                  f"grid {len(data['lats'])}x{len(data['lons'])}  "
                  f"leads {data['lead_hours']}")
            print(f"bounds {data['bounds']}")
            for key, grid in data["fields"].items():
                print("   " + summarise(key, grid))
        # Second call must come from cache.
        started = time.time()
        await client.get(f"/api/tropical/{sid}/fields", params={"hour": 0}, timeout=60)
        print("=" * 70)
        print(f"cached repeat: {time.time() - started:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
