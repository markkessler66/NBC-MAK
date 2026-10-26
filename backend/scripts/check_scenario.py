"""Exercise the what-if model against the live storm detail.

Runs several scenarios so the baseline can be sanity-checked against NHC and
the sign/size of each sensitivity inspected.
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
from app.services import scenario
from app.state import LATEST

logging.disable(logging.INFO)

CASES = [
    ("unchanged (must equal NHC)", {}),
    ("shear -15 kt", {"shear_delta_kt": -15}),
    ("shear +15 kt", {"shear_delta_kt": 15}),
    ("SST +1.5 C", {"sst_delta_c": 1.5}),
    ("SST -2 C", {"sst_delta_c": -2}),
    ("mid-levels +20%", {"rh_delta_pct": 20}),
    ("ridge 50% weaker", {"ridge_factor": 0.5}),
    ("ridge 40% stronger", {"ridge_factor": 1.4}),
    ("shear -12 and SST +1", {"shear_delta_kt": -12, "sst_delta_c": 1}),
]


def check_mpi() -> None:
    print("MPI curve (DeMaria & Kaplan):")
    for sst in (24, 26.5, 28, 29, 30, 31, 32):
        print(f"   SST {sst:>5.1f} C -> MPI {scenario.mpi_kt(sst):>6.0f} kt")
    print("\nGeostrophic flow from a 500 hPa height gradient:")
    for grad, lat in ((18, 17), (26, 28), (10, 20), (30, 35)):
        print(f"   {grad:>3.0f} m/1000 km at {lat:>3.0f} N -> "
              f"{scenario.geostrophic_kt(grad, lat):>5.1f} kt")


async def main() -> int:
    check_mpi()
    LATEST.tropical = await nhc.fetch_tropical()
    storms = LATEST.tropical["storms"]
    if not storms:
        print("no active storms")
        return 0

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for storm in storms[:2]:
            sid = storm["id"]
            print("\n" + "=" * 78)
            print(f"{sid} {storm['name']}  (now {storm.get('intensity_kt')} kt)")

            for label, params in CASES:
                resp = await client.get(f"/api/tropical/{sid}/scenario",
                                        params=params, timeout=180)
                if resp.status_code != 200:
                    print(f"  {label:<26} -> {resp.status_code} {resp.text[:120]}")
                    continue
                data = resp.json()
                if not data.get("available"):
                    print(f"  {label:<26} -> {data.get('reason')}")
                    continue
                points = data["points"]
                peak_nhc = max((p["nhc_wind_kt"] or 0) for p in points)
                peak_scn = max((p["scenario_wind_kt"] or 0) for p in points)
                last = points[-1]
                print(f"  {label:<26} peak NHC {peak_nhc:>5.0f} -> "
                      f"scenario {peak_scn:>5.0f} kt   "
                      f"end shift {last['shift_km'] or 0:>4} km "
                      f"{last['shift_compass'] or '--':<3}")

            # Show the raw model baseline against NHC once, to expose model bias.
            resp = await client.get(f"/api/tropical/{sid}/scenario", timeout=180)
            data = resp.json()
            if data.get("available"):
                print("\n  lead   NHC   toy-baseline   (bias)")
                for p in data["points"]:
                    nhc_kt = p["nhc_wind_kt"]
                    base = p["baseline_wind_kt"]
                    if nhc_kt is None or base is None:
                        continue
                    print(f"  {p['fcst_hour']:>4.0f}h {nhc_kt:>5.0f} {base:>13.0f}"
                          f"   {base - nhc_kt:>+7.0f}")
                print(f"\n  summary: {data['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
