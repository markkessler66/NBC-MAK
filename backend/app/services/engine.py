"""Consensus forecast engine.

Aligns every model onto a single hourly timeline, computes the multi-model
consensus (median) plus explicit disagreement (spread, per-model values), and
attaches GEFS ensemble percentile bands. The consensus is deliberately simple
and transparent for Phase 1; bias correction and learned model weighting come
later (spec Phase 5) once verification statistics accumulate.
"""
from datetime import timedelta
from zoneinfo import ZoneInfo

from ..config import FORECAST_VARS, settings
from ..state import LATEST
from ..util import floor_hour, iso, median, parse_iso_utc, utcnow

# Variables where a multi-model median/spread makes sense.
CONSENSUS_VARS = [v for v in FORECAST_VARS if v != "wind_dir"]


def confidence_label(spread: float | None, lead_h: float, n_models: int) -> str:
    """Temperature-spread-based confidence heuristic.

    Allowed spread grows with lead time (models legitimately diverge further
    out). Fewer than 3 agreeing models means limited evidence either way.
    """
    if spread is None or n_models < 2:
        return "unknown"
    if n_models < 3:
        return "limited"
    allowed = 3.0 + 0.06 * lead_h
    ratio = spread / allowed
    if ratio <= 0.7:
        return "high"
    if ratio <= 1.3:
        return "medium"
    return "low"


def _align(series: dict, index_of: dict[str, int], n: int) -> dict[str, list]:
    """Map a model's native time series onto the shared timeline."""
    aligned: dict[str, list] = {}
    positions = [index_of.get(t) for t in series["times"]]
    for var, col in series["values"].items():
        out: list = [None] * n
        for src_i, dst_i in enumerate(positions):
            if dst_i is not None and src_i < len(col):
                v = col[src_i]
                out[dst_i] = round(v, 2) if isinstance(v, (int, float)) else v
        aligned[var] = out
    return aligned


def build_forecast_payload(hours: int = 240) -> dict:
    now_h = floor_hour(utcnow())
    timeline = [now_h + timedelta(hours=i) for i in range(hours + 1)]
    timeline_iso = [iso(t) for t in timeline]
    index_of = {t: i for i, t in enumerate(timeline_iso)}
    n = len(timeline_iso)

    models_out: dict[str, dict] = {}
    for key, series in LATEST.model_series.items():
        models_out[key] = {
            "key": key,
            "label": series["label"],
            "is_ai": series.get("is_ai", False),
            "fetched_at": series["fetched_at"],
            "init_time": series.get("init_time"),
            "source": series.get("source"),
            "values": _align(series, index_of, n),
        }

    consensus: dict[str, dict[str, list]] = {}
    for var in CONSENSUS_VARS:
        med, lo, hi, spread, count = [], [], [], [], []
        for i in range(n):
            vals = [
                m["values"][var][i]
                for m in models_out.values()
                if var in m["values"] and m["values"][var][i] is not None
            ]
            if len(vals) >= 2:
                med.append(round(median(vals), 1))
                lo.append(round(min(vals), 1))
                hi.append(round(max(vals), 1))
                spread.append(round(max(vals) - min(vals), 1))
                count.append(len(vals))
            else:
                med.append(vals[0] if vals else None)
                lo.append(None)
                hi.append(None)
                spread.append(None)
                count.append(len(vals))
        consensus[var] = {"median": med, "min": lo, "max": hi, "spread": spread, "count": count}

    temp_conf = [
        confidence_label(consensus["temp_f"]["spread"][i], i, consensus["temp_f"]["count"][i])
        for i in range(n)
    ]

    ensemble_out = None
    ens = LATEST.ensemble
    if ens:
        ens_index = {t: i for i, t in enumerate(ens["times"])}
        aligned_pct: dict[str, dict[str, list]] = {}
        for var, bands in ens["percentiles"].items():
            aligned_pct[var] = {}
            for p, col in bands.items():
                out: list = [None] * n
                for i, t in enumerate(timeline_iso):
                    j = ens_index.get(t)
                    if j is not None:
                        out[i] = col[j]
                aligned_pct[var][p] = out
        ensemble_out = {
            "label": ens["label"],
            "members": ens["members"],
            "fetched_at": ens["fetched_at"],
            "percentiles": aligned_pct,
        }

    return {
        "generated_at": iso(utcnow()),
        "location": {"name": settings.home_name, "lat": settings.home_lat, "lon": settings.home_lon},
        "timeline": timeline_iso,
        "models": models_out,
        "consensus": consensus,
        "confidence_temp": temp_conf,
        "ensemble": ensemble_out,
        "daily": _daily_summary(timeline_iso, consensus, temp_conf),
    }


def _conditions_text(pop: float | None, cloud: float | None, cape: float | None) -> str:
    if pop is not None and pop >= 50:
        return "Storms" if (cape or 0) >= 1000 else "Rain likely"
    if pop is not None and pop >= 30:
        return "Chance rain"
    if cloud is None:
        return "—"
    if cloud >= 70:
        return "Cloudy"
    if cloud >= 40:
        return "Partly cloudy"
    return "Sunny"


def _daily_summary(timeline_iso: list[str], consensus: dict, temp_conf: list[str]) -> list[dict]:
    tz = ZoneInfo(settings.home_tz)
    by_date: dict[str, list[int]] = {}
    for i, t in enumerate(timeline_iso):
        local = parse_iso_utc(t).astimezone(tz)
        by_date.setdefault(local.date().isoformat(), []).append(i)

    med_t = consensus["temp_f"]["median"]
    spr_t = consensus["temp_f"]["spread"]
    med_pop = consensus["precip_prob"]["median"]
    med_pr = consensus["precip_in"]["median"]
    med_cloud = consensus["cloud_pct"]["median"]
    med_cape = consensus["cape"]["median"]

    days = []
    for date_str, idxs in sorted(by_date.items()):
        temps = [med_t[i] for i in idxs if med_t[i] is not None]
        if len(temps) < 6:
            continue
        # Daytime (roughly 7 AM–7 PM local) drives the "conditions" summary.
        day_idxs = [i for i in idxs if 7 <= parse_iso_utc(timeline_iso[i]).astimezone(tz).hour <= 19]
        pops = [med_pop[i] for i in (day_idxs or idxs) if med_pop[i] is not None]
        clouds = [med_cloud[i] for i in (day_idxs or idxs) if med_cloud[i] is not None]
        capes = [med_cape[i] for i in (day_idxs or idxs) if med_cape[i] is not None]
        precip = [med_pr[i] for i in idxs if med_pr[i] is not None]
        spreads = [spr_t[i] for i in idxs if spr_t[i] is not None]
        confs = [temp_conf[i] for i in idxs if temp_conf[i] not in ("unknown", "limited")]

        pop_max = max(pops) if pops else None
        cloud_avg = sum(clouds) / len(clouds) if clouds else None
        days.append({
            "date": date_str,
            "hi": max(temps),
            "lo": min(temps),
            "pop": pop_max,
            "precip_in": round(sum(precip), 2) if precip else None,
            "temp_spread_max": max(spreads) if spreads else None,
            "conditions": _conditions_text(pop_max, cloud_avg, max(capes) if capes else None),
            "confidence": max(set(confs), key=confs.count) if confs else "unknown",
        })
    return days
