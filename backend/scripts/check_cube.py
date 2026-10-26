"""Offline check of the field-cube assembly, with no upstream calls.

The cube is what keeps the map inside Open-Meteo's daily quota: one sample of
the whole track, sliced per lead hour. That slicing is pure bookkeeping over
index arithmetic, so it is worth pinning down without spending quota on it.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingest import tropical_fields as tf  # noqa: E402

BASE = datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)
LEADS = [0, 12, 24, 36, 48, 60, 72, 96, 120]
TIMES = [BASE + timedelta(hours=h) for h in LEADS]

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def fake_point(lat: float, lon: float) -> dict:
    """An Open-Meteo-shaped hourly series whose values encode their own hour.

    Shear is built to rise linearly with lead time so a mis-sliced frame shows
    up as an obviously wrong number rather than a plausible one.
    """
    stamps, s850, d850, s200, d200, rh, mslp, hgt, s500, d500 = ([] for _ in range(10))
    for step in range(0, 145):
        when = BASE + timedelta(hours=step)
        stamps.append(when.strftime("%Y-%m-%dT%H:%M"))
        # Both levels blow the same way, so the shear magnitude is just the
        # speed difference: 5 + step, a value that can only be right if the
        # frame was sliced at the correct timestep.
        s850.append(10.0)
        d850.append(270.0)
        s200.append(15.0 + step)
        d200.append(270.0)
        s500.append(20.0)
        d500.append(90.0)
        rh.append(50.0 + step * 0.1)
        mslp.append(1010.0 + step * 0.01)
        hgt.append(5800.0 + lat)
    return {"hourly": {
        "time": stamps,
        "wind_speed_850hPa": s850, "wind_direction_850hPa": d850,
        "wind_speed_200hPa": s200, "wind_direction_200hPa": d200,
        "wind_speed_500hPa": s500, "wind_direction_500hPa": d500,
        "relative_humidity_700hPa": rh, "pressure_msl": mslp,
        "geopotential_height_500hPa": hgt,
    }}


async def main() -> None:
    lat_range, lon_range = (10.0, 26.0), (-120.0, -100.0)

    captured: dict[str, object] = {}

    async def fake_fetch(url, coords, hourly, **extra):
        captured["n_calls"] = int(captured.get("n_calls", 0)) + 1
        captured["n_locations"] = int(captured.get("n_locations", 0)) + len(coords)
        captured["extra"] = extra
        return [fake_point(la, lo) for la, lo in coords]

    tf._fetch_batched = fake_fetch  # type: ignore[assignment]

    sst = {"lats": [10.0, 20.0, 30.0], "lons": [-120.0, -110.0, -100.0],
           "grid": [[28.0] * 3 for _ in range(3)]}

    print("cube assembly")
    cube = await tf.sample_cube(lat_range, lon_range, TIMES, sst=sst)

    n_cells = len(cube["lats"]) * len(cube["lons"])
    check("one upstream pass for all lead hours", captured["n_calls"] == 1,
          f"{captured['n_calls']} call(s), {captured['n_locations']} locations")
    check("locations equal grid cells, not cells x hours",
          captured["n_locations"] == n_cells,
          f"{n_cells} cells vs {captured['n_locations']} billed")
    check("cost is a fraction of per-hour sampling",
          captured["n_locations"] * len(LEADS) > captured["n_locations"],
          f"saved {n_cells * (len(LEADS) - 1)} locations")
    check("one frame per requested time", len(cube["frames"]) == len(TIMES))
    check("time window spans the whole track",
          captured["extra"].get("start_hour", "").endswith("18:00")
          and captured["extra"].get("end_hour", "").startswith("2026-09-05"),
          str({k: captured["extra"].get(k) for k in ("start_hour", "end_hour")}))

    print("\nper-frame slicing (shear must equal 5 + lead hour)")
    for lead, frame in zip(LEADS, cube["frames"]):
        got = frame["shear_kt"][0][0]
        check(f"+{lead:3d} h", got is not None and abs(got - (5.0 + lead)) < 0.01,
              f"got {got}")

    print("\nfield population")
    last = cube["frames"][-1]
    for key in ("sst_c", "rh_700_pct", "mslp_mb", "height_500_m",
                "steering_kt", "favourability"):
        values = [v for row in last[key] for v in row if v is not None]
        check(f"{key} populated", len(values) == n_cells,
              f"{len(values)}/{n_cells}")
    check("sst interpolated from the coarse grid",
          last["sst_c"][0][0] == 28.0, f"got {last['sst_c'][0][0]}")

    print("\ngrid geometry")
    check("stays inside the point cap", n_cells <= tf.MAX_POINTS,
          f"{len(cube['lats'])}x{len(cube['lons'])} = {n_cells}")
    check("covers the requested extent",
          cube["bounds"]["south"] <= lat_range[0] + tf.DEFAULT_STEP_DEG
          and cube["bounds"]["north"] >= lat_range[1] - tf.DEFAULT_STEP_DEG,
          str(cube["bounds"]))

    print("\nmisaligned times degrade to null, not to a wrong hour")
    off = await tf.sample_cube(lat_range, lon_range,
                               [BASE - timedelta(days=40)], sst=sst)
    check("out-of-range time yields nulls",
          off["frames"][0]["shear_kt"][0][0] is None,
          f"got {off['frames'][0]['shear_kt'][0][0]}")

    print("\n" + ("all checks passed" if not failures
                  else f"{len(failures)} FAILED: {failures}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
