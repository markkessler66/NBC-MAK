"""Forecast/observation archiving for verification.

Every model refresh stores point forecasts keyed by (model, run_hour,
target_time); duplicates within the same hour are ignored. This builds the
historical forecast archive from day one (spec: verification matters more
than the UI).
"""
from datetime import timedelta

from ..config import ARCHIVE_VARS, settings
from ..db import bulk_insert_ignore, session_scope
from ..orm import Observation, PointForecast
from ..util import floor_hour, parse_iso_utc, round_hour, utcnow


def archive_model_series(series: dict) -> int:
    """Persist one model snapshot's hourly point forecasts.

    Native NOAA series carry the true model initialization time; API-sourced
    series fall back to the fetch hour as a run proxy.
    """
    run_hour = floor_hour(parse_iso_utc(series.get("init_time") or series["fetched_at"]))
    max_target = run_hour + timedelta(hours=settings.archive_max_lead_hours)

    rows = []
    values = series["values"]
    for i, t_iso in enumerate(series["times"]):
        target = parse_iso_utc(t_iso)
        if target < run_hour or target > max_target:
            continue
        row = {
            "model": series["key"],
            "run_hour": run_hour,
            "target_time": target,
            "lead_hours": (target - run_hour).total_seconds() / 3600.0,
        }
        has_data = False
        for var in ARCHIVE_VARS:
            col = values.get(var)
            v = col[i] if col is not None and i < len(col) else None
            row[var] = v
            has_data = has_data or v is not None
        if has_data:
            rows.append(row)

    if not rows:
        return 0
    with session_scope() as session:
        return bulk_insert_ignore(session, PointForecast, rows)


def archive_observation(obs: dict) -> int:
    """Persist one surface observation (idempotent per station+timestamp)."""
    obs_time = parse_iso_utc(obs["obs_time"])
    if utcnow() - obs_time > timedelta(hours=6):
        return 0  # stale station clock or feed; don't pollute verification
    row = {
        "station": obs["station"],
        "obs_time": obs_time,
        "obs_hour": round_hour(obs_time),
        "temp_f": obs.get("temp_f"),
        "dewpoint_f": obs.get("dewpoint_f"),
        "rh": obs.get("rh"),
        "wind_mph": obs.get("wind_mph"),
        "gust_mph": obs.get("gust_mph"),
        "pressure_mb": obs.get("pressure_mb"),
    }
    with session_scope() as session:
        return bulk_insert_ignore(session, Observation, [row])
