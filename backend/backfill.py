"""Historical backfill: seed the verification archive and the future Phase-5
training set without waiting months for live collection.

Sources:
  * Iowa Environmental Mesonet ASOS archive  -> historical KADS observations
  * Open-Meteo "Previous Runs" API           -> lagged model forecasts
    (temperature_2m_previous_dayN = what the run from N days earlier predicted
    for that hour). Run attribution is day-granular, so rows are flagged
    origin='backfill' and leads are exact multiples of 24 h. Leakage-free by
    construction: every value was produced N days before its valid time.

Usage (from backend/):
    .venv\\Scripts\\python backfill.py --days 365
"""
import argparse
import asyncio
import csv
import io
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings
from app.db import bulk_insert_ignore, init_db, session_scope
from app.orm import Observation, PointForecast
from app.util import round_hour, utcnow

MESONET_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
PREV_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"

# Open-Meteo previous-runs variables -> internal keys
BACKFILL_VARS = {
    "temperature_2m": "temp_f",
    "dew_point_2m": "dewpoint_f",
    "relative_humidity_2m": "rh",
    "wind_speed_10m": "wind_mph",
}

# model key -> (open-meteo model name, available day lags)
BACKFILL_MODELS = {
    "hrrr": ("gfs_hrrr", [1]),                # HRRR only reaches ~18-48 h
    "gfs": ("gfs_global", [1, 2, 3, 4, 5, 6, 7]),
    "ecmwf_ifs": ("ecmwf_ifs025", [1, 2, 3, 4, 5, 6, 7]),
}

KT_TO_MPH = 1.15078


async def backfill_observations(client: httpx.AsyncClient, start: datetime, end: datetime) -> int:
    """Historical METARs for the Addison, TX ASOS (matches the live station)."""
    params = {
        "station": "ADS",
        "data": "tmpf,dwpf,relh,sknt,gust,mslp",
        "year1": start.year, "month1": start.month, "day1": start.day,
        "year2": end.year, "month2": end.month, "day2": end.day,
        "tz": "Etc/UTC", "format": "onlycomma",
        "latlon": "no", "missing": "empty", "trace": "empty",
    }
    print(f"[obs] requesting KADS METARs {start.date()} .. {end.date()} from IEM ...")
    resp = await client.get(MESONET_URL, params=params, timeout=300)
    resp.raise_for_status()

    def f(row: dict, key: str) -> float | None:
        v = row.get(key, "")
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    rows = []
    for row in csv.DictReader(io.StringIO(resp.text)):
        try:
            obs_time = datetime.strptime(row["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        temp = f(row, "tmpf")
        if temp is None:
            continue
        sknt, gust = f(row, "sknt"), f(row, "gust")
        rows.append({
            "station": "KADS",
            "obs_time": obs_time,
            "obs_hour": round_hour(obs_time),
            "temp_f": temp,
            "dewpoint_f": f(row, "dwpf"),
            "rh": f(row, "relh"),
            "wind_mph": round(sknt * KT_TO_MPH, 1) if sknt is not None else None,
            "gust_mph": round(gust * KT_TO_MPH, 1) if gust is not None else None,
            "pressure_mb": f(row, "mslp"),
        })

    inserted = 0
    with session_scope() as session:
        for i in range(0, len(rows), 5000):
            inserted += bulk_insert_ignore(session, Observation, rows[i:i + 5000])
    print(f"[obs] parsed {len(rows)} METARs, inserted (attempted) {inserted}")
    return inserted


async def backfill_model(client: httpx.AsyncClient, key: str, start: datetime, end: datetime) -> int:
    om_name, lags = BACKFILL_MODELS[key]
    hourly = [f"{v}_previous_day{n}" for v in BACKFILL_VARS for n in lags]

    total = 0
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + timedelta(days=90), end)
        params = {
            "latitude": settings.home_lat,
            "longitude": settings.home_lon,
            "hourly": ",".join(hourly),
            "models": om_name,
            "start_date": chunk_start.strftime("%Y-%m-%d"),
            "end_date": chunk_end.strftime("%Y-%m-%d"),
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "timezone": "UTC",
        }
        resp = await client.get(PREV_RUNS_URL, params=params, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        h = data.get("hourly") or {}
        times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
                 for t in h.get("time", [])]

        # rows keyed by (run_hour, target) so all variables land in one row
        by_key: dict[tuple, dict] = {}
        for om_var, our_var in BACKFILL_VARS.items():
            for n in lags:
                col = h.get(f"{om_var}_previous_day{n}")
                if col is None:
                    continue
                for t, v in zip(times, col):
                    if v is None:
                        continue
                    run_hour = t - timedelta(hours=24 * n)
                    row = by_key.setdefault((run_hour, t), {
                        "model": key,
                        "run_hour": run_hour,
                        "target_time": t,
                        "lead_hours": 24.0 * n,
                        "origin": "backfill",
                        # executemany needs identical keys on every row
                        **{v_key: None for v_key in BACKFILL_VARS.values()},
                    })
                    row[our_var] = round(float(v), 2)

        rows = list(by_key.values())
        with session_scope() as session:
            for i in range(0, len(rows), 5000):
                total += bulk_insert_ignore(session, PointForecast, rows[i:i + 5000])
        print(f"[{key}] {chunk_start.date()} .. {chunk_end.date()}: {len(rows)} rows")
        chunk_start = chunk_end + timedelta(days=1)
        await asyncio.sleep(1.0)  # be polite to the free API
    return total


async def main(days: int) -> None:
    init_db()
    end = utcnow() - timedelta(days=1)   # exclude today; live archive owns it
    start = end - timedelta(days=days)
    async with httpx.AsyncClient(headers={"User-Agent": settings.user_agent}) as client:
        await backfill_observations(client, start, end)
        for key in BACKFILL_MODELS:
            n = await backfill_model(client, key, start, end)
            print(f"[{key}] total rows attempted: {n}")
    print("backfill complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()
    asyncio.run(main(args.days))
