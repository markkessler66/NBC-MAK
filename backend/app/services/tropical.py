"""Tropical cyclone diagnostics: turn sampled environment into readable reasoning.

The thresholds here are the conventional operational ones (roughly 26.5 C for
the sea-surface temperature a cyclone needs, 10/20/30 kt bands for deep-layer
shear, mid-level humidity around 50-70%). Every metric carries the number, the
category it falls in, and why it matters, so nothing is asserted that the
displayed value does not support.

This is model-derived guidance, deliberately kept separate from the official
NHC forecast it sits beside: it explains what GFS shows around the storm, and
where that agrees or disagrees with the advisory.
"""
import asyncio
import logging
import time

from ..ingest import nhc_gis, tropical_env, tropical_fields
from ..ingest.tropical_env import angular_diff, bearing_deg, compass, haversine_km
from ..state import LATEST
from ..util import iso, parse_iso_utc, utcnow

log = logging.getLogger("weatherlab.tropical")

# Detail bundles are advisory-driven: NHC issues every 6 h (intermediate every
# 3 h), so half an hour of cache never hides a new advisory for long.
_DETAIL_TTL = 1800
_detail_cache: dict[str, tuple[float, dict]] = {}
_detail_locks: dict[str, asyncio.Lock] = {}

# Field grids are hundreds of Open-Meteo points, so they are cached harder and
# keyed by the lead hour the map is showing.
# Keyed by storm: one cube holds every lead hour. Six hours matches the GFS
# cycle, so a refresh lands roughly when there is genuinely new model data.
_FIELDS_TTL = 6 * 3600
_DEGRADED_TTL = 600
_fields_cache: dict[str, tuple[float, dict]] = {}
_fields_locks: dict[str, asyncio.Lock] = {}

SST_FLOOR_C = 26.5  # conventional minimum to sustain a tropical cyclone

KM_PER_NM = 1.852


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _scale(value: float, worst: float, best: float) -> float:
    """Linear 0-100 score between a worst and best anchor (either ordering)."""
    if worst == best:
        return 50.0
    return _clamp((value - worst) / (best - worst) * 100.0)


# ---- metric construction -----------------------------------------------------

def _metric(key: str, label: str, display: str, category: str | None,
            tone: str, note: str, value=None, score: float | None = None) -> dict:
    return {
        "key": key, "label": label, "value": value, "display": display,
        "category": category, "tone": tone, "note": note, "score": score,
    }


def _sst_metric(point: dict) -> dict:
    sst = point.get("sst_c")
    if point.get("over_land"):
        return _metric(
            "sst", "Sea-surface temp", "over land", "No ocean heat source", "bad",
            "The centre is over land, so the surface heat and moisture flux that "
            "drives a tropical cyclone is cut off.", score=0.0)
    if sst is None:
        return _metric("sst", "Sea-surface temp", "—", None, "neutral",
                       "No SST sample available at this position.")
    delta = sst - SST_FLOOR_C
    if sst >= 29.0:
        category, tone = "Exceptionally warm", "good"
    elif sst >= 28.0:
        category, tone = "Very warm", "good"
    elif sst >= SST_FLOOR_C:
        category, tone = "Supportive", "good"
    elif sst >= 25.0:
        category, tone = "Marginal", "warn"
    else:
        category, tone = "Too cool", "bad"
    sign = "above" if delta >= 0 else "below"
    return _metric(
        "sst", "Sea-surface temp", f"{sst:.1f} °C / {point['sst_f']:.0f} °F",
        category, tone,
        f"{abs(delta):.1f} °C {sign} the ~{SST_FLOOR_C} °C a tropical cyclone needs "
        "to sustain itself.",
        value=sst, score=_scale(sst, 24.0, 30.0))


def _shear_metric(point: dict) -> dict:
    shear = point.get("shear")
    if not shear:
        return _metric("shear", "Deep-layer shear", "—", None, "neutral",
                       "No upper-air sample available at this position.")
    magnitude = shear["magnitude_kt"]
    downshear = shear["toward_compass"]
    if magnitude < 10:
        category, tone = "Low", "good"
        note = "Low enough for the core to stay vertically stacked — the classic setup for intensification."
    elif magnitude < 20:
        category, tone = "Moderate", "warn"
        note = (f"Enough to tilt the vortex and push convection downshear (toward the {downshear}), "
                "which usually slows but does not stop intensification.")
    elif magnitude < 30:
        category, tone = "High", "bad"
        note = (f"Strong enough to displace convection {downshear} of the centre and "
                "ventilate the core — weakening is favoured.")
    else:
        category, tone = "Extreme", "bad"
        note = f"Hostile; convection is likely sheared well {downshear} of the low-level centre."
    return _metric(
        "shear", "Deep-layer shear (850–200 hPa)", f"{magnitude:.0f} kt → {downshear}",
        category, tone, note, value=magnitude, score=_scale(magnitude, 35.0, 5.0))


def _moisture_metric(point: dict) -> dict:
    rh = point.get("rh_700_pct")
    if rh is None:
        return _metric("moisture", "Mid-level humidity", "—", None, "neutral",
                       "No humidity sample available at this position.")
    if rh >= 70:
        category, tone = "Moist", "good"
        note = "Moist mid-levels; dry-air entrainment is not a limiting factor."
    elif rh >= 55:
        category, tone = "Marginal", "warn"
        note = "Somewhat dry aloft; entrainment can undercut convective bursts."
    elif rh >= 40:
        category, tone = "Dry", "bad"
        note = "Dry mid-levels will feed downdrafts and fight core convection."
    else:
        category, tone = "Very dry", "bad"
        note = "Very dry mid-levels — a strong constraint on organisation."
    return _metric("moisture", "Mid-level humidity (700 hPa)", f"{rh:.0f}%",
                   category, tone, note, value=rh, score=_scale(rh, 35.0, 75.0))


def _model_fidelity_metric(point: dict, storm: dict) -> dict:
    """How well GFS resolves this storm — the caveat on its own guidance."""
    modelled = point.get("model_central_pressure_mb")
    observed = storm.get("pressure_mb")
    if modelled is None:
        return _metric("model_core", "GFS central pressure", "—", None, "neutral",
                       "No model pressure sample at the centre.")
    if observed is None:
        return _metric("model_core", "GFS central pressure", f"{modelled:.0f} mb",
                       None, "neutral", "No NHC pressure to compare against.")
    error = modelled - observed
    if abs(error) < 5:
        category, tone = "Well resolved", "good"
        note = ("GFS has the core within 5 mb of the analysed pressure, so its "
                "intensity guidance for this storm is credible.")
    elif error > 0:
        category, tone = "Under-resolved", "warn"
        note = (f"GFS is {error:.0f} mb too shallow — at its resolution it cannot "
                "fit this core, so treat its intensity forecast as a floor and "
                "its steering as the more useful output.")
    else:
        category, tone = "Over-deepened", "warn"
        note = (f"GFS is {abs(error):.0f} mb deeper than analysed, so it may be "
                "overdoing the circulation's strength and depth.")
    return _metric("model_core", "GFS central pressure",
                   f"{modelled:.0f} mb vs {observed:.0f} mb analysed",
                   category, tone, note, value=modelled)


def _outflow_metric(point: dict) -> dict:
    temp = point.get("outflow_temp_c")
    if temp is None:
        return _metric("outflow", "Outflow temperature (200 hPa)", "—", None, "neutral",
                       "No upper-level temperature sample available.")
    if temp <= -55:
        category, tone = "Very cold", "good"
    elif temp <= -50:
        category, tone = "Typical", "neutral"
    else:
        category, tone = "Warm", "warn"
    return _metric(
        "outflow", "Outflow temperature (200 hPa)", f"{temp:.1f} °C", category, tone,
        "The larger the temperature drop from sea surface to outflow layer, the "
        "more thermodynamic potential the storm has to work with. Tropical values "
        "usually sit between −50 and −56 °C.", value=temp)


# ---- intensity reasoning -----------------------------------------------------

def _trend(along_track: list[dict], getter, hours: int = 72):
    """First value and the value nearest `hours` out, for a simple trend read."""
    usable = [(p["fcst_hour"], getter(p)) for p in along_track if getter(p) is not None]
    if len(usable) < 2:
        return None
    start = usable[0]
    later = [u for u in usable if u[0] <= hours] or usable
    end = later[-1]
    if end[0] == start[0]:
        return None
    return {"from": start[1], "to": end[1], "hours": end[0]}


def _intensity_diagnosis(env: dict, storm: dict, track_points: list[dict]) -> dict:
    current = env["current"]
    along = env.get("along_track") or []
    metrics = [_sst_metric(current), _shear_metric(current),
               _moisture_metric(current), _outflow_metric(current),
               _model_fidelity_metric(current, storm)]
    scored = [m["score"] for m in metrics if m.get("score") is not None]
    score = round(sum(scored) / len(scored)) if scored else None

    # Intensity is set by whichever ingredient is missing, not by the average of
    # them. Warm water is a necessary condition, so a storm over sub-threshold
    # SST cannot intensify however low the shear is — averaging would hide that.
    limiter = None
    if score is not None:
        sst = current.get("sst_c")
        shear_kt = (current.get("shear") or {}).get("magnitude_kt")
        if current.get("over_land"):
            score, limiter = min(score, 10), "the centre being over land"
        elif sst is not None and sst < SST_FLOOR_C:
            score = min(score, 38)
            limiter = f"water below the ~{SST_FLOOR_C} °C a cyclone needs"
        elif shear_kt is not None and shear_kt >= 30:
            score, limiter = min(score, 30), "hostile deep-layer shear"

    if score is None:
        verdict, tone = "Insufficient data", "neutral"
    elif score >= 70:
        verdict, tone = "Favourable for strengthening", "good"
    elif score >= 45:
        verdict, tone = "Mixed — near steady state", "warn"
    else:
        verdict, tone = "Unfavourable — weakening favoured", "bad"

    parts: list[str] = []
    if current.get("over_land"):
        parts.append("The centre is over land, so the ocean heat source that drives the "
                     "circulation is already cut off and weakening is the expected outcome.")
    else:
        sst, shear, moist = metrics[0], metrics[1], metrics[2]
        if sst.get("value") is not None:
            parts.append(f"Water under the centre is {sst['display']}, {sst['note'][0].lower()}{sst['note'][1:]}")
        if shear.get("value") is not None:
            parts.append(f"Deep-layer shear is {shear['display'].split(' →')[0]} "
                         f"({shear['category'].lower()}). {shear['note']}")
        if moist.get("value") is not None:
            parts.append(moist["note"])

    shear_trend = _trend(along, lambda p: (p.get("shear") or {}).get("magnitude_kt"))
    sst_trend = _trend(along, lambda p: p.get("sst_c"))
    trend_bits = []
    if shear_trend and abs(shear_trend["to"] - shear_trend["from"]) >= 6:
        direction = "rises" if shear_trend["to"] > shear_trend["from"] else "eases"
        trend_bits.append(f"shear {direction} from {shear_trend['from']:.0f} to "
                          f"{shear_trend['to']:.0f} kt by {shear_trend['hours']} h")
    if sst_trend and abs(sst_trend["to"] - sst_trend["from"]) >= 0.8:
        direction = "warms" if sst_trend["to"] > sst_trend["from"] else "cools"
        trend_bits.append(f"SST {direction} from {sst_trend['from']:.1f} to "
                          f"{sst_trend['to']:.1f} °C")
    if limiter:
        parts.append(f"The limiting factor is {limiter} — that caps intensity "
                     "regardless of how favourable the other ingredients are.")
    if trend_bits:
        parts.append("Along the official track, " + " and ".join(trend_bits) + ".")

    landfall = next((p for p in along if p["fcst_hour"] > 0 and p.get("over_land")), None)
    if landfall:
        parts.append(f"The track is over land by {landfall['fcst_hour']} h, which caps "
                     "intensity from that point on regardless of the rest of the pattern.")

    forecast_winds = [(p["fcst_hour"], p["wind_kt"]) for p in track_points
                      if p.get("wind_kt") is not None and not p.get("post_tropical")]
    if len(forecast_winds) > 1:
        peak_hour, peak_wind = max(forecast_winds, key=lambda w: w[1])
        now_wind = forecast_winds[0][1]
        if peak_wind > now_wind:
            parts.append(f"NHC's own forecast peaks at {peak_wind:.0f} kt near {peak_hour} h "
                         f"(now {now_wind:.0f} kt).")
        elif peak_wind <= now_wind:
            parts.append(f"NHC's forecast holds {now_wind:.0f} kt as the peak and weakens "
                         "the system thereafter.")

    return {
        "score": score,
        "verdict": verdict,
        "tone": tone,
        "limiter": limiter,
        "metrics": metrics,
        "narrative": " ".join(parts),
    }


# ---- steering reasoning ------------------------------------------------------

def _track_geometry(points: list[dict]) -> dict:
    """Heading, forward speed, and any recurvature implied by the official points."""
    usable = [p for p in points if p.get("lat") is not None and p.get("lon") is not None]
    if len(usable) < 2:
        return {}
    legs = []
    for a, b in zip(usable, usable[1:]):
        hours = b["fcst_hour"] - a["fcst_hour"]
        distance = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
        legs.append({
            "heading": bearing_deg(a["lat"], a["lon"], b["lat"], b["lon"]),
            "distance_km": distance,
            "hours": hours,
            "speed_kt": (distance / KM_PER_NM / hours) if hours else None,
        })
    speeds = [leg["speed_kt"] for leg in legs if leg["speed_kt"] is not None]
    return {
        "initial_heading_deg": round(legs[0]["heading"]),
        "final_heading_deg": round(legs[-1]["heading"]),
        "turn_deg": round(angular_diff(legs[0]["heading"], legs[-1]["heading"]) or 0),
        "mean_speed_kt": round(sum(speeds) / len(speeds), 1) if speeds else None,
        "total_distance_km": round(sum(leg["distance_km"] for leg in legs)),
    }


def _feature_place(feature: dict) -> str:
    """Describe where a pattern feature is, honestly about grid-edge hits."""
    where = f"{feature['distance_km']:,} km {feature['bearing_compass']}"
    return f"toward {feature['bearing_compass']} (beyond {where})" if feature.get("on_edge") else where


def _pressure_metrics(pattern: dict | None) -> list[dict]:
    if not pattern:
        return []
    metrics = []
    high = pattern.get("surface_high")
    if high and high.get("pressure_mb") is not None:
        flank = compass((high["bearing_deg"] + 180) % 360)
        metrics.append(_metric(
            "surface_high", "Surface high",
            f"{high['pressure_mb']:.0f} mb · {_feature_place(high)}",
            "Centre off-grid" if high.get("on_edge") else "Located", "neutral",
            f"The storm sits on the high's {flank} flank, where the clockwise flow "
            "around it pushes the system along."))
    ridge = pattern.get("mid_ridge")
    if ridge and ridge.get("height_500_m") is not None:
        metrics.append(_metric(
            "mid_ridge", "500 hPa ridge",
            f"{ridge['height_500_m']:,} m · {_feature_place(ridge)}",
            "Centre off-grid" if ridge.get("on_edge") else "Located", "neutral",
            "The mid-level ridge is the dominant steering feature for a mature "
            "cyclone; its position sets which way the storm is turned."))
    trough = pattern.get("mid_trough")
    if trough and trough.get("height_500_m") is not None:
        distance = trough["distance_km"]
        close = distance < 1400 and not trough.get("on_edge")
        metrics.append(_metric(
            "mid_trough", "Nearest 500 hPa trough",
            f"{trough['height_500_m']:,} m · {_feature_place(trough)}",
            "Close" if close else "Distant", "warn" if close else "neutral",
            "A trough eroding the ridge is what lets a storm turn poleward and "
            "eventually recurve; the closer it is, the sooner that can happen."))
    return metrics


def _steering_diagnosis(env: dict, storm: dict, track_points: list[dict]) -> dict:
    current = env["current"]
    steering = current.get("steering")
    low_level = (current.get("flow") or {}).get("850")
    motion_deg = storm.get("movement_dir_deg")
    intensity_kt = storm.get("intensity_kt")
    geometry = _track_geometry(track_points)

    # Shallow systems are carried by the low-level flow; deep ones by the
    # 850-200 mean. Which layer we compare motion against matters.
    shallow = intensity_kt is not None and intensity_kt < 50
    reference = low_level if (shallow and low_level and low_level.get("toward_deg") is not None) else steering
    reference_label = ("low-level (850 hPa) flow" if reference is low_level
                       else "deep-layer mean (850–200 hPa) flow")

    metrics: list[dict] = []
    if steering and steering.get("speed_kt") is not None:
        metrics.append(_metric(
            "dlm", "Deep-layer mean flow",
            f"{steering['speed_kt']:.0f} kt → {steering['toward_compass']} "
            f"({steering['toward_deg']:.0f}°)", None, "neutral",
            "Mass-weighted 850–200 hPa flow — the layer that steers a mature "
            "tropical cyclone.", value=steering["speed_kt"]))
    for level, label in (("850", "Low-level flow (850 hPa)"),
                         ("500", "Mid-level flow (500 hPa)")):
        flow = (current.get("flow") or {}).get(level) or {}
        if flow.get("speed_kt") is not None:
            metrics.append(_metric(
                f"flow{level}", label,
                f"{flow['speed_kt']:.0f} kt → {flow['toward_compass']} ({flow['toward_deg']:.0f}°)",
                None, "neutral",
                "Shallow systems track closest to the low-level flow; deeper ones "
                "follow the mid- and upper-level flow.", value=flow["speed_kt"]))
    gradient = current.get("height_500_gradient")
    if gradient:
        flank = compass((gradient["toward_higher_deg"] + 180) % 360)
        metrics.append(_metric(
            "height_gradient", "500 hPa height gradient",
            f"+{gradient['per_1000km']:.0f} m/1,000 km toward {gradient['toward_higher_compass']}",
            None, "neutral",
            f"Heights rise toward the {gradient['toward_higher_compass']}, so the ridge lies "
            f"that way and the storm is on its {flank} flank. Measured across the "
            "sampling ring, so it holds whether or not the ridge centre is nearby.",
            value=gradient["per_1000km"]))
    metrics.extend(_pressure_metrics(env.get("pattern")))

    parts: list[str] = []
    if motion_deg is not None:
        speed = storm.get("movement_speed_mph")
        speed_text = f" at {speed:.0f} mph" if speed is not None else ""
        parts.append(f"The centre is moving toward {motion_deg:.0f}° "
                     f"({compass(motion_deg)}){speed_text}.")

    agreement = None
    if reference and reference.get("toward_deg") is not None:
        parts.append(f"GFS puts the {reference_label} at {reference['speed_kt']:.0f} kt "
                     f"toward {reference['toward_deg']:.0f}° ({reference['toward_compass']}).")
        difference = angular_diff(motion_deg, reference["toward_deg"])
        if difference is not None:
            agreement = round(difference)
            if difference <= 25:
                parts.append("That closely matches the observed motion, so the storm is "
                             "being steered by the flow the model shows.")
            elif difference <= 60:
                parts.append(f"That is {agreement}° off the observed motion — broadly "
                             "consistent, with the usual beta drift and centre-fixing noise.")
            else:
                parts.append(f"That differs from the observed motion by {agreement}°, which "
                             "typically means the circulation is still shallow or poorly "
                             "defined and not yet locked to the steering flow.")

    pattern = env.get("pattern") or {}
    ridge = pattern.get("mid_ridge")
    trough = pattern.get("mid_trough")
    if gradient:
        flank = compass((gradient["toward_higher_deg"] + 180) % 360)
        parts.append(f"500 hPa heights rise toward the {gradient['toward_higher_compass']} at "
                     f"{gradient['per_1000km']:.0f} m per 1,000 km, so the ridge lies that way "
                     f"and the storm is riding its {flank} flank — that gradient is what the "
                     "steering flow above is flowing along.")
    if ridge and ridge.get("height_500_m") is not None and not ridge.get("on_edge"):
        parts.append(f"The ridge itself peaks {ridge['distance_km']:,} km to the "
                     f"{ridge['bearing_compass']} at {ridge['height_500_m']:,} m.")
    high = pattern.get("surface_high")
    if high and high.get("pressure_mb") is not None and not high.get("on_edge"):
        parts.append(f"At the surface, a {high['pressure_mb']:.0f} mb high is centred "
                     f"{high['distance_km']:,} km {high['bearing_compass']}.")
    if trough and trough.get("height_500_m") is not None and not trough.get("on_edge"):
        parts.append(f"The nearest mid-level trough ({trough['height_500_m']:,} m) is "
                     f"{trough['distance_km']:,} km to the {trough['bearing_compass']}; "
                     "a trough eroding the ridge is what would let the track turn poleward.")

    if geometry.get("turn_deg") is not None and geometry["turn_deg"] >= 25:
        parts.append(f"NHC's track bends {geometry['turn_deg']}° over the forecast period, "
                     f"from {compass(geometry['initial_heading_deg'])} initially to "
                     f"{compass(geometry['final_heading_deg'])} at the end.")
    elif geometry.get("initial_heading_deg") is not None:
        parts.append(f"The official track holds a steady {compass(geometry['initial_heading_deg'])} "
                     "heading through the forecast period.")
    if geometry.get("mean_speed_kt"):
        parts.append(f"Mean forward speed along the forecast track is "
                     f"{geometry['mean_speed_kt']:.0f} kt.")

    return {
        "reference_layer": reference_label,
        "agreement_deg": agreement,
        "geometry": geometry,
        "metrics": metrics,
        "narrative": " ".join(parts),
    }


def _headline(storm: dict, intensity: dict, steering: dict) -> str:
    name = f"{storm.get('classification_label')} {storm.get('name')}".strip()
    bits = [f"{name}: {intensity['verdict'].lower()}."]
    current = intensity["metrics"]
    sst = next((m for m in current if m["key"] == "sst"), None)
    shear = next((m for m in current if m["key"] == "shear"), None)
    drivers = []
    if shear and shear.get("category"):
        drivers.append(f"{shear['category'].lower()} shear ({shear['display'].split(' →')[0]})")
    if sst and sst.get("value") is not None:
        drivers.append(f"{sst['value']:.1f} °C water")
    elif sst and sst.get("category") == "No ocean heat source":
        drivers.append("no ocean heat source")
    if intensity.get("limiter"):
        bits.append(f"Held back by {intensity['limiter']}.")
    elif drivers:
        bits.append("Driven by " + " over ".join(drivers) + ".")
    if steering.get("geometry", {}).get("initial_heading_deg") is not None:
        bits.append(f"Steering carries it {compass(steering['geometry']['initial_heading_deg'])}.")
    return " ".join(bits)


# ---- wind field --------------------------------------------------------------

def _wind_field(advisory: dict | None) -> dict | None:
    """Current wind radii summarised as a size measure, in nm and km."""
    if not advisory:
        return None
    radii = advisory.get("initial_radii_nm") or {}
    if not radii:
        return None
    out = {}
    for threshold, quadrants in radii.items():
        values = [v for v in quadrants.values() if v]
        out[threshold] = {
            "quadrants_nm": quadrants,
            "max_nm": max(values) if values else 0,
            "mean_nm": round(sum(quadrants.values()) / 4),
            "mean_km": round(sum(quadrants.values()) / 4 * KM_PER_NM),
        }
    ts_mean = out.get("34", {}).get("mean_nm")
    size = None
    if ts_mean:
        if ts_mean < 60:
            size = "Small"
        elif ts_mean < 120:
            size = "Average"
        elif ts_mean < 200:
            size = "Large"
        else:
            size = "Very large"
    return {"radii": out, "size_class": size,
            "note": "Radii are the greatest extent of that wind anywhere in the "
                    "quadrant, so they describe the wind field's size rather than "
                    "its core strength."}


# ---- assembly ----------------------------------------------------------------

async def _fetch_advisory_products(storm: dict) -> tuple[dict | None, dict | None]:
    """Forecast advisory (wind radii) and forecast discussion, best-effort."""
    from ..http_client import get_text

    async def _load(url: str | None, parser):
        if not url:
            return None
        try:
            return parser(await get_text(url))
        except Exception as exc:
            log.warning("advisory product %s failed: %s", url, exc)
            return None

    return await asyncio.gather(
        _load(storm.get("forecast_advisory_url"), nhc_gis.parse_forecast_advisory),
        _load(storm.get("discussion_url"), nhc_gis.parse_discussion),
    )


async def _build_detail(storm: dict) -> dict:
    track = storm.get("track") or {}
    track_points = track.get("points") or []

    (advisory, discussion), environment = await asyncio.gather(
        _fetch_advisory_products(storm),
        tropical_env.sample_environment(storm, track_points),
    )

    intensity = _intensity_diagnosis(environment, storm, track_points)
    steering = _steering_diagnosis(environment, storm, track_points)

    return {
        "storm": storm,
        "fetched_at": iso(utcnow()),
        "advisory": advisory,
        "discussion": discussion,
        "wind_field": _wind_field(advisory),
        "environment": environment,
        "diagnostics": {
            "headline": _headline(storm, intensity, steering),
            "intensity": intensity,
            "steering": steering,
            "caveat": "Environmental diagnostics are sampled from GFS and the "
                      "Open-Meteo marine feed at the storm's position and along "
                      "NHC's official forecast points. They explain the pattern "
                      "the model shows — they are not a substitute for the NHC "
                      "forecast or its reasoning.",
        },
    }


def find_storm(storm_id: str) -> dict | None:
    payload = LATEST.tropical or {}
    wanted = storm_id.lower()
    return next((s for s in payload.get("storms", [])
                 if (s.get("id") or "").lower() == wanted), None)


async def get_storm_detail(storm_id: str, force: bool = False) -> dict | None:
    """Cached detail bundle; concurrent callers share one upstream fetch."""
    storm = find_storm(storm_id)
    if storm is None:
        return None
    key = (storm.get("id") or storm_id).lower()

    lock = _detail_locks.setdefault(key, asyncio.Lock())
    async with lock:
        cached = _detail_cache.get(key)
        advisory_changed = bool(cached) and (
            cached[1]["storm"].get("advisory_num") != storm.get("advisory_num"))
        if cached and not force and not advisory_changed and time.time() - cached[0] < _DETAIL_TTL:
            return cached[1]
        detail = await _build_detail(storm)
        _detail_cache[key] = (time.time(), detail)
        return detail


def _track_position(storm: dict, hour: int) -> tuple[float, float, str]:
    """Where the map should be centred for a lead hour, and the time it is valid."""
    now = utcnow()
    if hour <= 0:
        return storm["lat"], storm["lon"], iso(now)
    for point in ((storm.get("track") or {}).get("points") or []):
        if point.get("fcst_hour") == hour and point.get("lat") is not None:
            valid = point.get("valid_time")
            return point["lat"], point["lon"], valid or iso(now)
    return storm["lat"], storm["lon"], iso(now)


def _track_extent(storm: dict, margin: float) -> tuple[tuple[float, float], tuple[float, float]]:
    """Latitude and longitude span covering every forecast position, plus margin."""
    lats = [storm["lat"]]
    lons = [storm["lon"]]
    for point in ((storm.get("track") or {}).get("points") or []):
        if point.get("lat") is not None and point.get("lon") is not None:
            lats.append(point["lat"])
            lons.append(point["lon"])
    return ((max(-80.0, min(lats) - margin), min(80.0, max(lats) + margin)),
            (min(lons) - margin, max(lons) + margin))


def available_lead_hours(storm: dict) -> list[int]:
    points = (storm.get("track") or {}).get("points") or []
    hours = sorted({int(p["fcst_hour"]) for p in points
                    if p.get("fcst_hour") is not None and p.get("lat") is not None})
    return [h for h in hours if h <= 120]


async def _storm_cube(storm: dict, storm_id: str, force: bool) -> dict:
    """Every lead hour of the mapped environment, sampled and cached as one unit.

    One upstream pass covers the whole track and all lead times, so switching
    lead hour in the UI is free after the first request.
    """
    lock = _fields_locks.setdefault(storm_id, asyncio.Lock())
    async with lock:
        cached = _fields_cache.get(storm_id)
        if cached and not force and time.time() - cached[0] < _FIELDS_TTL:
            return cached[1]

        hours = available_lead_hours(storm)
        times = [parse_iso_utc(_track_position(storm, h)[2]) for h in hours]
        lat_range, lon_range = _track_extent(storm, tropical_fields.TRACK_MARGIN_DEG)
        sst = await tropical_fields.sst_grid(storm_id, lat_range, lon_range)
        cube = await tropical_fields.sample_cube(lat_range, lon_range, times, sst=sst)
        cube["lead_hours"] = hours
        # A cube missing its atmosphere is worth serving but not worth keeping
        # for a full GFS cycle: expire it soon so it refills once quota returns.
        age = time.time() - (_FIELDS_TTL - _DEGRADED_TTL if cube.get("degraded") else 0)
        _fields_cache[storm_id] = (age, cube)
        return cube


async def get_storm_fields(storm_id: str, hour: int = 0,
                           force: bool = False) -> dict | None:
    """Gridded environment around a storm at one lead time, for map shading."""
    storm = find_storm(storm_id)
    if storm is None or storm.get("lat") is None:
        return None
    key = (storm.get("id") or storm_id).lower()

    try:
        cube = await _storm_cube(storm, key, force)
    except tropical_env.BudgetExhausted as exc:
        return {
            "storm_id": storm.get("id"), "fcst_hour": int(hour),
            "lead_hours": available_lead_hours(storm), "unavailable": str(exc),
            "note": ("The upstream model feed is over its request quota, so the "
                     "map layers are unavailable until it resets. Everything "
                     "else on this page is unaffected."),
        }

    hours = cube.get("lead_hours") or [0]
    index = min(range(len(hours)), key=lambda i: abs(hours[i] - int(hour)))
    lat, lon, _ = _track_position(storm, hours[index])
    return {
        **{k: v for k, v in cube.items() if k not in ("frames", "valid_times")},
        "fields": cube["frames"][index],
        "valid_time": cube["valid_times"][index],
        "storm_id": storm.get("id"),
        "fcst_hour": hours[index],
        "centre": {"lat": lat, "lon": lon},
    }


def prune_cache(active_ids: set[str]) -> None:
    """Drop bundles for storms NHC has stopped carrying."""
    tropical_fields.drop_sst_cache(active_ids)
    for key in list(_fields_cache):
        if key not in active_ids:
            _fields_cache.pop(key, None)
            _fields_locks.pop(key, None)
    for key in list(_detail_cache):
        if key not in active_ids:
            _detail_cache.pop(key, None)
            _detail_locks.pop(key, None)
