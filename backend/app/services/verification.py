"""Forecast verification: MAE / RMSE / bias per model per lead-time bucket.

Forecasts are joined to hourly-averaged observations at the same valid hour.
A persistence baseline ("tomorrow = right now") is computed from observations
alone so model skill is always judged against a naive reference (spec §21).
"""
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from ..config import MODELS_BY_KEY, VERIFIABLE_VARS
from ..db import session_scope
from ..util import utcnow

# (label, lead_lo_inclusive, lead_hi_exclusive, representative_lead)
BUCKETS = [
    ("1h", 0.0, 2.0, 1),
    ("3h", 2.0, 4.5, 3),
    ("6h", 4.5, 9.0, 6),
    ("12h", 9.0, 18.0, 12),
    ("24h", 18.0, 36.0, 24),
    ("48h", 36.0, 60.0, 48),
    ("72h", 60.0, 96.0, 72),
    ("7d", 96.0, 192.0, 168),
]


def _stats(errors: list[float]) -> dict:
    n = len(errors)
    mae = sum(abs(e) for e in errors) / n
    rmse = math.sqrt(sum(e * e for e in errors) / n)
    bias = sum(errors) / n
    return {"n": n, "mae": round(mae, 2), "rmse": round(rmse, 2), "bias": round(bias, 2)}


def _bucket_label(lead: float) -> str | None:
    for label, lo, hi, _ in BUCKETS:
        if lo <= lead < hi:
            return label
    return None


def _as_dt(value) -> datetime:
    """Raw SQL rows return SQLite datetimes as strings; normalize to aware UTC."""
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_verification(var: str = "temp_f", days: int = 30) -> dict:
    if var not in VERIFIABLE_VARS:
        raise ValueError(f"variable {var!r} is not verifiable against observations")
    cutoff = utcnow() - timedelta(days=days)

    with session_scope() as session:
        # Hourly-averaged observations (multiple stations/reports per hour).
        obs_rows = session.execute(
            text(f"""
                SELECT obs_hour, AVG({var}) AS ov
                FROM observations
                WHERE {var} IS NOT NULL
                GROUP BY obs_hour
            """)
        ).all()
        obs_by_hour = {r[0]: r[1] for r in obs_rows}

        fc_rows = session.execute(
            text(f"""
                SELECT f.model, f.lead_hours, f.{var} AS fv, o.ov
                FROM point_forecasts f
                JOIN (
                    SELECT obs_hour, AVG({var}) AS ov
                    FROM observations
                    WHERE {var} IS NOT NULL
                    GROUP BY obs_hour
                ) o ON o.obs_hour = f.target_time
                WHERE f.run_hour >= :cutoff AND f.{var} IS NOT NULL
            """),
            {"cutoff": cutoff},
        ).all()

    # model -> bucket -> error list
    errors: dict[str, dict[str, list[float]]] = {}
    for model, lead, fv, ov in fc_rows:
        bucket = _bucket_label(lead)
        if bucket is None or ov is None:
            continue
        errors.setdefault(model, {}).setdefault(bucket, []).append(fv - ov)

    models_out = {}
    for model, buckets in errors.items():
        spec = MODELS_BY_KEY.get(model)
        all_errors = [e for lst in buckets.values() for e in lst]
        models_out[model] = {
            "label": spec.label if spec else model,
            "buckets": {b: _stats(lst) for b, lst in buckets.items()},
            "overall": _stats(all_errors) if all_errors else None,
        }

    # Persistence baseline: predict obs(t + lead) = obs(t).
    obs_by_dt = {_as_dt(h): v for h, v in obs_by_hour.items()}
    persistence: dict[str, dict] = {}
    for label, _, _, rep_lead in BUCKETS:
        errs = []
        for h, v in obs_by_dt.items():
            target_val = obs_by_dt.get(h + timedelta(hours=rep_lead))
            if target_val is not None:
                errs.append(v - target_val)
        if errs:
            persistence[label] = _stats(errs)
    if persistence:
        models_out["persistence"] = {
            "label": "Persistence (baseline)",
            "buckets": persistence,
            "overall": None,
        }

    # Which model currently has the lowest MAE per bucket (min sample size 20).
    best = {}
    for label, *_ in BUCKETS:
        candidates = [
            (m["buckets"][label]["mae"], key)
            for key, m in models_out.items()
            if key != "persistence" and label in m["buckets"] and m["buckets"][label]["n"] >= 20
        ]
        if candidates:
            best[label] = min(candidates)[1]

    return {
        "variable": var,
        "window_days": days,
        "computed_at": utcnow().isoformat(),
        "bucket_order": [b[0] for b in BUCKETS],
        "models": models_out,
        "best_by_bucket": best,
        "sample_note": (
            "Statistics require accumulated history; treat buckets with small n "
            "as provisional. Models are only comparable on matched samples."
        ),
    }
