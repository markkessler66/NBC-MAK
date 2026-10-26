"""A sandbox for "what if the environment were different?".

There is always a storm that outruns the guidance, and the interesting question
is which ingredient was responsible. This module lets one be dialled up or down
— shear, ocean heat, mid-level moisture, the strength of the steering ridge —
and reports what that change would do to intensity and track.

It is a toy model and is labelled as one everywhere it surfaces. Two choices
keep it honest rather than merely plausible:

*Anchoring.* The number shown is never the toy model's own forecast. The model
is run twice, once on the sampled environment and once on the adjusted one, and
only the *difference* between those runs is applied to NHC's official forecast.
Systematic error in the toy model largely cancels, and with every slider at
zero the scenario reproduces the official forecast exactly. What the user reads
is "this change is worth about +18 kt", which is a question a simple model can
answer far more credibly than "this storm will be 123 kt".

*Physical parameterisation.* Intensity relaxes toward a potential intensity set
by SST (DeMaria & Kaplan's empirical MPI curve), discounted for shear and dry
air. Track is advected by the deep-layer steering actually sampled around the
storm, perturbed by the change in the geostrophic flow implied by scaling the
500 hPa height gradient. Nothing here is tuned to make a pretty answer.
"""
from __future__ import annotations

import math

from ..ingest.tropical_env import bearing_deg, compass, destination, haversine_km
from ..util import parse_iso_utc

# DeMaria & Kaplan (1994) maximum potential intensity against SST, in m/s.
MPI_A, MPI_B, MPI_C, MPI_T0 = 28.2, 55.8, 0.1813, 30.0
MS_TO_KT = 1.94384

# Relaxation timescales toward the target intensity. A mature cyclone carries
# real inertia: moved over marginal water it spins down over days, not hours,
# which is why NHC keeps a major hurricane going across 25 C water. Land is the
# exception — once the moisture source is cut the core comes apart quickly.
TAU_UP_H = 26.0
TAU_DOWN_H = 36.0
TAU_DOWN_LAND_H = 10.0
MAX_RATE_UP_KT_H = 2.2        # ~53 kt/day, beyond even most rapid intensification
MAX_RATE_DOWN_KT_H = 1.6      # ~38 kt/day, a fast but observed weakening rate
MAX_RATE_DOWN_LAND_KT_H = 4.0

# Below the threshold the ocean can no longer sustain a warm core, but the
# ceiling has to fall off smoothly: a cliff here made the model dump a Category
# 4 to tropical-storm strength in a day over 25 C water, which is not what
# either the physics or the official forecasts do.
SST_TAPER_FLOOR_C = 22.0
SST_THRESHOLD_C = 26.5

LAND_CAP_KT = 25.0
SUBSTEP_H = 3.0

# Stand-ins for when a sample is missing. Assuming a perfect environment would
# let the model sprint toward maximum potential intensity precisely when it
# knows least, so unknown ingredients take an unremarkable tropical value.
FALLBACK_SHEAR_KT = 12.0
FALLBACK_RH_PCT = 60.0

OMEGA = 7.292e-5
GRAVITY = 9.81

LIMITS = {
    "shear_delta_kt": (-30.0, 30.0),
    "sst_delta_c": (-3.0, 3.0),
    "rh_delta_pct": (-30.0, 30.0),
    "ridge_factor": (0.4, 1.6),
}


def clamp_adjustments(raw: dict) -> dict:
    out = {}
    for key, (low, high) in LIMITS.items():
        default = 1.0 if key == "ridge_factor" else 0.0
        try:
            value = float(raw.get(key, default))
        except (TypeError, ValueError):
            value = default
        out[key] = max(low, min(high, value))
    return out


NEUTRAL = {"shear_delta_kt": 0.0, "sst_delta_c": 0.0,
           "rh_delta_pct": 0.0, "ridge_factor": 1.0}


# ---- physics ----------------------------------------------------------------

def mpi_kt(sst_c: float) -> float:
    """Empirical maximum potential intensity for a given sea-surface temperature."""
    return (MPI_A + MPI_B * math.exp(MPI_C * (sst_c - MPI_T0))) * MS_TO_KT


def _shear_factor(shear_kt: float) -> float:
    """Fraction of potential intensity still reachable under this much shear."""
    return max(0.12, min(1.0, 1.0 - (shear_kt - 5.0) / 36.0))


def _humidity_factor(rh_pct: float) -> float:
    return max(0.55, min(1.0, 0.55 + 0.45 * (rh_pct - 38.0) / 30.0))


def target_intensity_kt(sst_c: float | None, shear_kt: float | None,
                        rh_pct: float | None, over_land: bool) -> float:
    """Intensity the environment can support, before any time dependence."""
    if over_land:
        return LAND_CAP_KT
    if sst_c is None:
        return 0.0
    ceiling = mpi_kt(sst_c)
    if sst_c < SST_THRESHOLD_C:
        span = SST_THRESHOLD_C - SST_TAPER_FLOOR_C
        ceiling *= max(0.15, min(1.0, (sst_c - SST_TAPER_FLOOR_C) / span))
    factor = (_shear_factor(FALLBACK_SHEAR_KT if shear_kt is None else shear_kt)
              * _humidity_factor(FALLBACK_RH_PCT if rh_pct is None else rh_pct))
    return max(0.0, ceiling * factor)


def geostrophic_kt(gradient_per_1000km: float, lat: float) -> float:
    """Geostrophic flow implied by a 500 hPa height gradient, in knots.

    Sanity check against the live data: an 18 m/1,000 km gradient at 17 N gives
    about 8 kt, which is what the annulus-averaged deep-layer mean was actually
    measuring for that storm. The two agreeing is why the ridge slider can be
    expressed as a change to this gradient.
    """
    f = 2 * OMEGA * math.sin(math.radians(max(3.0, abs(lat))))
    return (GRAVITY / f) * (gradient_per_1000km / 1.0e6) * MS_TO_KT


# ---- interpolation over the sampled stops ------------------------------------

def _stop_hours(stops: list[dict]) -> list[float]:
    return [float(s.get("fcst_hour") or 0) for s in stops]


def _interp_env(stops: list[dict], hours: list[float], t: float) -> dict:
    """Environment at an arbitrary lead time, linear between sampled stops."""
    if t <= hours[0]:
        lo = hi = 0
        frac = 0.0
    elif t >= hours[-1]:
        lo = hi = len(stops) - 1
        frac = 0.0
    else:
        hi = next(i for i, h in enumerate(hours) if h >= t)
        lo = max(0, hi - 1)
        span = hours[hi] - hours[lo]
        frac = 0.0 if span <= 0 else (t - hours[lo]) / span

    def blend(getter):
        a, b = getter(stops[lo]), getter(stops[hi])
        if a is None:
            return b
        if b is None:
            return a
        return a + (b - a) * frac

    shear = blend(lambda s: (s.get("shear") or {}).get("magnitude_kt"))
    steer = stops[lo].get("steering") or {}
    steer_hi = stops[hi].get("steering") or {}
    gradient = blend(lambda s: (s.get("height_500_gradient") or {}).get("per_1000km"))
    grad_dir = (stops[lo].get("height_500_gradient") or {}).get("toward_higher_deg")

    return {
        "sst_c": blend(lambda s: s.get("sst_c")),
        "shear_kt": shear,
        "rh_700_pct": blend(lambda s: s.get("rh_700_pct")),
        # Land is a step change, not something to average across.
        "over_land": bool(stops[hi if frac > 0.5 else lo].get("over_land")),
        "steer_speed_kt": blend(lambda s: (s.get("steering") or {}).get("speed_kt")),
        "steer_toward_deg": _blend_angle(steer.get("toward_deg"),
                                         steer_hi.get("toward_deg"), frac),
        "gradient_per_1000km": gradient,
        "gradient_toward_deg": grad_dir,
        "lat": blend(lambda s: s.get("lat")),
        "lon": blend(lambda s: s.get("lon")),
    }


def _blend_angle(a: float | None, b: float | None, frac: float) -> float | None:
    if a is None:
        return b
    if b is None:
        return a
    delta = ((b - a + 180) % 360) - 180
    return (a + delta * frac) % 360


# ---- integrations ------------------------------------------------------------

def _run_intensity(stops: list[dict], start_kt: float, adj: dict,
                   horizon: float) -> dict[float, float]:
    """Intensity every SUBSTEP_H hours out to the horizon, keyed by lead hour."""
    hours = _stop_hours(stops)
    value = start_kt
    out = {0.0: value}
    t = 0.0
    while t < horizon:
        env = _interp_env(stops, hours, t + SUBSTEP_H / 2)
        sst = None if env["sst_c"] is None else env["sst_c"] + adj["sst_delta_c"]
        # Adjustments apply to the fallback too, so a slider still bites on a
        # storm whose environment sampling came back short.
        shear = max(0.0, (env["shear_kt"] if env["shear_kt"] is not None
                          else FALLBACK_SHEAR_KT) + adj["shear_delta_kt"])
        rh = max(1.0, min(100.0, (env["rh_700_pct"] if env["rh_700_pct"] is not None
                                  else FALLBACK_RH_PCT) + adj["rh_delta_pct"]))

        target = target_intensity_kt(sst, shear, rh, env["over_land"])
        if target > value:
            tau, cap = TAU_UP_H, MAX_RATE_UP_KT_H
        elif env["over_land"]:
            tau, cap = TAU_DOWN_LAND_H, MAX_RATE_DOWN_LAND_KT_H
        else:
            tau, cap = TAU_DOWN_H, MAX_RATE_DOWN_KT_H
        rate = (target - value) / tau
        value = max(0.0, value + max(-cap, min(cap, rate)) * SUBSTEP_H)
        t += SUBSTEP_H
        out[round(t, 3)] = value
    return out


def _run_track(stops: list[dict], adj: dict, horizon: float) -> dict[float, tuple[float, float]]:
    """Positions every SUBSTEP_H hours, advected by (perturbed) steering."""
    hours = _stop_hours(stops)
    lat, lon = stops[0]["lat"], stops[0]["lon"]
    out = {0.0: (lat, lon)}
    t = 0.0
    while t < horizon:
        env = _interp_env(stops, hours, t + SUBSTEP_H / 2)
        speed = env["steer_speed_kt"]
        toward = env["steer_toward_deg"]
        if speed is None or toward is None:
            out[round(t + SUBSTEP_H, 3)] = (lat, lon)
            t += SUBSTEP_H
            continue

        u = speed * math.sin(math.radians(toward))
        v = speed * math.cos(math.radians(toward))

        # Scaling the height gradient scales the geostrophic flow it implies;
        # the difference from the unscaled case is the steering perturbation.
        gradient = env["gradient_per_1000km"]
        grad_dir = env["gradient_toward_deg"]
        if gradient is not None and grad_dir is not None and adj["ridge_factor"] != 1.0:
            g_speed = geostrophic_kt(gradient, lat)
            # Geostrophic flow runs along the contours with high heights to the
            # right in the northern hemisphere.
            g_toward = (grad_dir - 90.0) % 360
            delta = (adj["ridge_factor"] - 1.0) * g_speed
            u += delta * math.sin(math.radians(g_toward))
            v += delta * math.cos(math.radians(g_toward))

        new_speed = math.hypot(u, v)
        new_toward = (math.degrees(math.atan2(u, v)) + 360) % 360
        lat, lon = destination(lat, lon, new_toward, new_speed * 1.852 * SUBSTEP_H)
        t += SUBSTEP_H
        out[round(t, 3)] = (lat, lon)
    return out


def _nearest(series: dict[float, object], hour: float):
    if not series:
        return None
    key = min(series, key=lambda k: abs(k - hour))
    return series[key]


# ---- narrative ---------------------------------------------------------------

def _describe(adj: dict) -> list[str]:
    bits = []
    if adj["shear_delta_kt"]:
        verb = "weaker" if adj["shear_delta_kt"] < 0 else "stronger"
        bits.append(f"deep-layer shear {abs(adj['shear_delta_kt']):.0f} kt {verb}")
    if adj["sst_delta_c"]:
        verb = "cooler" if adj["sst_delta_c"] < 0 else "warmer"
        bits.append(f"sea surface {abs(adj['sst_delta_c']):.1f} °C {verb}")
    if adj["rh_delta_pct"]:
        verb = "drier" if adj["rh_delta_pct"] < 0 else "moister"
        bits.append(f"mid-levels {abs(adj['rh_delta_pct']):.0f}% {verb}")
    if adj["ridge_factor"] != 1.0:
        pct = abs(adj["ridge_factor"] - 1.0) * 100
        verb = "weaker" if adj["ridge_factor"] < 1 else "stronger"
        bits.append(f"steering ridge {pct:.0f}% {verb}")
    return bits


def _summarise(points: list[dict], adj: dict) -> str:
    changes = _describe(adj)
    if not changes:
        return ("Every control is at the observed value, so the scenario is NHC's "
                "official forecast unchanged. Move a slider to see what that "
                "ingredient is worth.")

    lead = "With " + ", ".join(changes) + ": "
    parts = []

    # Peak-against-peak hides any weakening scenario on a storm already at its
    # forecast peak, so report where the two curves diverge most instead.
    divergences = [(p["scenario_wind_kt"] - p["nhc_wind_kt"], p)
                   for p in points
                   if p["scenario_wind_kt"] is not None and p["nhc_wind_kt"] is not None]
    biggest = max(divergences, key=lambda d: abs(d[0]), default=None)
    if biggest is None or abs(biggest[0]) < 3:
        parts.append("intensity barely changes from the official forecast")
    else:
        delta, point = biggest
        direction = "stronger" if delta > 0 else "weaker"
        parts.append(f"the biggest intensity change is {abs(delta):.0f} kt {direction} "
                     f"at {point['fcst_hour']:.0f} h "
                     f"({point['nhc_wind_kt']:.0f} kt officially, "
                     f"{point['scenario_wind_kt']:.0f} kt here)")

    final = points[-1] if points else None
    shift = (final or {}).get("shift_km") or 0
    if shift >= 40:
        parts.append(f"and by {final['fcst_hour']:.0f} h the centre sits {shift:.0f} km "
                     f"to the {final['shift_compass']} of the official track")
    elif any((p.get("shift_km") or 0) >= 40 for p in points):
        parts.append("and the track wanders from the official one mid-period before "
                     "converging again")
    else:
        parts.append("and the track barely moves")
    return lead + ", ".join(parts) + "."


# ---- entry point -------------------------------------------------------------

def build_scenario(detail: dict, raw_adjustments: dict) -> dict:
    """Run the toy model twice and express the difference against NHC's forecast."""
    adj = clamp_adjustments(raw_adjustments)
    environment = detail.get("environment") or {}
    stops = [s for s in (environment.get("along_track") or [])
             if s.get("lat") is not None and s.get("lon") is not None]
    if len(stops) < 2:
        return {"available": False,
                "reason": "This system has no forecast track to run a scenario against.",
                "adjustments": adj}

    storm = detail.get("storm") or {}
    start_kt = float(storm.get("intensity_kt") or stops[0].get("nhc_wind_kt") or 30.0)
    horizon = max(_stop_hours(stops))

    base_v = _run_intensity(stops, start_kt, NEUTRAL, horizon)
    scen_v = _run_intensity(stops, start_kt, adj, horizon)
    base_p = _run_track(stops, NEUTRAL, horizon)
    scen_p = _run_track(stops, adj, horizon)

    points = []
    for stop in stops:
        hour = float(stop.get("fcst_hour") or 0)
        nhc_kt = stop.get("nhc_wind_kt")

        b_v = _nearest(base_v, hour)
        s_v = _nearest(scen_v, hour)
        # Anchor on the official forecast: only the model's own delta is applied.
        anchored = None
        if nhc_kt is not None and b_v is not None and s_v is not None:
            anchored = max(0.0, nhc_kt + (s_v - b_v))

        b_lat, b_lon = _nearest(base_p, hour) or (None, None)
        s_lat, s_lon = _nearest(scen_p, hour) or (None, None)
        lat = lon = shift = shift_dir = None
        if None not in (b_lat, b_lon, s_lat, s_lon):
            # Same anchoring for position: displace NHC's point by the change.
            offset_km = haversine_km(b_lat, b_lon, s_lat, s_lon)
            if offset_km > 0.01:
                offset_dir = bearing_deg(b_lat, b_lon, s_lat, s_lon)
                lat, lon = destination(stop["lat"], stop["lon"], offset_dir, offset_km)
            else:
                lat, lon = stop["lat"], stop["lon"]
            shift = round(offset_km)
            shift_dir = bearing_deg(stop["lat"], stop["lon"], lat, lon) if shift else None

        points.append({
            "fcst_hour": hour,
            "valid_time": stop.get("valid_time"),
            "nhc_wind_kt": nhc_kt,
            "nhc_lat": stop["lat"],
            "nhc_lon": stop["lon"],
            "baseline_wind_kt": round(b_v, 1) if b_v is not None else None,
            "scenario_wind_kt": round(anchored, 1) if anchored is not None else None,
            "model_wind_kt": round(s_v, 1) if s_v is not None else None,
            "scenario_lat": round(lat, 2) if lat is not None else None,
            "scenario_lon": round(lon, 2) if lon is not None else None,
            "shift_km": shift,
            "shift_compass": compass(shift_dir) if shift_dir is not None else None,
            "sst_c": stop.get("sst_c"),
            "shear_kt": (stop.get("shear") or {}).get("magnitude_kt"),
            "rh_700_pct": stop.get("rh_700_pct"),
        })

    return {
        "available": True,
        "adjustments": adj,
        "limits": {k: {"min": v[0], "max": v[1]} for k, v in LIMITS.items()},
        "points": points,
        "summary": _summarise(points, adj),
        "changed": bool(_describe(adj)),
        "method": (
            "The model relaxes intensity toward a potential intensity set by SST "
            "(DeMaria & Kaplan's empirical curve), discounted for shear and dry "
            "air, and advects the centre with the deep-layer steering sampled "
            "around the storm. It is run twice — once on the observed "
            "environment, once on the adjusted one — and only the difference "
            "between those two runs is applied to NHC's official forecast."),
        "caveat": (
            "This is a deliberately simple sensitivity experiment, not a "
            "forecast. It has no inner-core dynamics, no ocean feedback, no eyewall "
            "replacement, and it assumes the change you dial in applies uniformly "
            "along the whole track. Treat the direction and rough size of the "
            "response as the useful output, not the exact numbers."),
    }
