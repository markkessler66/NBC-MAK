"""Parsers for the NHC GIS and text advisory products behind a storm's forecast.

The cone of uncertainty and the official forecast track ship as KMZ (a zipped
KML); the forecast/discussion advisories ship as fixed-format text. The
geometries involved are trivial — one polygon per forecast period, one
polyline, and a handful of point placemarks — so the standard library handles
them and the project avoids an OGR/geopandas dependency.

Everything here is pure parsing: no network calls, so it is unit-testable
against saved fixtures.
"""
import html
import io
import re
import zipfile
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

from ..units import kt_to_mph
from ..util import iso

# NHC states valid times in the storm's local zone, identified by abbreviation
# only, so we carry our own table rather than guessing from the coordinates.
_TZ_OFFSETS = {
    "UTC": 0, "GMT": 0, "Z": 0,
    "ADT": -3, "AST": -4,
    "EDT": -4, "EST": -5,
    "CDT": -5, "CST": -6,
    "MDT": -6, "MST": -7,
    "PDT": -7, "PST": -8,
    "AKDT": -8, "AKST": -9,
    "HDT": -9, "HST": -10,
    "SST": -11, "CHST": 10,
}

_VALID_AT_RE = re.compile(
    r"(\d{1,2}):(\d{2})\s*(AM|PM)\s+([A-Za-z]{2,4})\s+([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})",
    re.I,
)
_LOCATION_RE = re.compile(r"Location:\s*(-?[\d.]+)\s*([NS])?\s*,\s*(-?[\d.]+)\s*([EW])?", re.I)
_WIND_RE = re.compile(r"Maximum Wind:\s*(\d+)\s*knots", re.I)
_GUST_RE = re.compile(r"Wind Gusts:\s*(\d+)\s*knots", re.I)
_HOUR_RE = re.compile(r"(\d+)\s*hr\s*Forecast", re.I)


# ---- Saffir-Simpson helpers ---------------------------------------------------

def saffir_simpson(wind_kt: float | None) -> int | None:
    """Hurricane category for a 1-minute sustained wind, or None below 64 kt."""
    if wind_kt is None:
        return None
    for threshold, category in ((137, 5), (113, 4), (96, 3), (83, 2), (64, 1)):
        if wind_kt >= threshold:
            return category
    return None


def stage_code(wind_kt: float | None, post_tropical: bool = False) -> str:
    """Two-letter stage code consistent with NHC's `classification` field."""
    if post_tropical:
        return "PC"
    if wind_kt is None:
        return "LO"
    if wind_kt >= 96:
        return "MH"
    if wind_kt >= 64:
        return "HU"
    if wind_kt >= 34:
        return "TS"
    return "TD"


def intensity_label(wind_kt: float | None, post_tropical: bool = False) -> str:
    if post_tropical:
        return "Post-tropical"
    cat = saffir_simpson(wind_kt)
    if cat:
        return f"Category {cat} hurricane"
    if wind_kt is None:
        return "Unknown"
    if wind_kt >= 34:
        return "Tropical storm"
    return "Tropical depression"


# ---- KML plumbing ------------------------------------------------------------

def _local(tag: str) -> str:
    """Local element name; NHC mixes KML 2.1 and 2.2 namespaces between products."""
    return tag.rsplit("}", 1)[-1]


def _iter_local(elem, name: str) -> list:
    return [e for e in elem.iter() if _local(e.tag) == name]


def _read_kml(raw: bytes):
    """Return the parsed root of the KML inside a KMZ (or of a bare KML)."""
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
            if not names:
                return None
            raw = zf.read(names[0])
    return ElementTree.fromstring(raw)


def _coords(text: str | None, precision: int = 3) -> list[list[float]]:
    """KML `lon,lat[,alt]` tuples -> [[lon, lat], ...].

    Rounded to ~100 m and de-duplicated: cone rings carry ~700 vertices at
    5 decimal places, which is an order of magnitude more precision than a
    basin-scale map can show.
    """
    out: list[list[float]] = []
    for token in (text or "").split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            point = [round(float(parts[0]), precision), round(float(parts[1]), precision)]
        except ValueError:
            continue
        if out and out[-1] == point:
            continue
        out.append(point)
    return out


def _simplify(points: list[list[float]], tolerance: float = 0.01) -> list[list[float]]:
    """Ramer-Douglas-Peucker in degrees, iterative to stay recursion-safe.

    Cone rings arrive as ~1000-2000 vertices tracing smooth arcs. At a 0.01
    degree (~1 km) tolerance the drawn shape is indistinguishable at any zoom
    a basin map uses, for roughly a tenth of the payload.
    """
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        ax, ay = points[start]
        bx, by = points[end]
        dx, dy = bx - ax, by - ay
        norm = (dx * dx + dy * dy) ** 0.5
        worst, worst_i = -1.0, start
        for i in range(start + 1, end):
            px, py = points[i]
            if norm == 0:
                dist = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
            else:
                dist = abs(dy * (px - ax) - dx * (py - ay)) / norm
            if dist > worst:
                worst, worst_i = dist, i
        if worst > tolerance:
            keep[worst_i] = True
            stack.extend(((start, worst_i), (worst_i, end)))
    return [p for p, k in zip(points, keep) if k]


def _extended_data(placemark) -> dict[str, str]:
    data = {}
    for node in _iter_local(placemark, "Data"):
        name = node.get("name")
        value = next((v.text for v in _iter_local(node, "value")), None)
        if name:
            data[name.strip()] = (value or "").strip()
    return data


def _cdata_cells(placemark) -> list[str]:
    """Text of every <td> in a placemark description, tags stripped."""
    desc = next((d.text for d in _iter_local(placemark, "description") if d.text), None)
    if not desc:
        return []
    cells = re.findall(r"<td[^>]*>(.*?)</td>", desc, re.S | re.I)
    return [html.unescape(re.sub(r"<[^>]+>", " ", c)).strip() for c in cells]


def _parse_valid_at(cell: str) -> datetime | None:
    """`Valid at: 7:00 PM CDT September 01, 2026` -> aware UTC datetime."""
    m = _VALID_AT_RE.search(cell)
    if not m:
        return None
    hour12, minute, meridiem, tz, month, day, year = m.groups()
    offset = _TZ_OFFSETS.get(tz.upper())
    if offset is None:
        return None
    hour = int(hour12) % 12 + (12 if meridiem.upper() == "PM" else 0)
    try:
        local = datetime.strptime(f"{month} {day} {year} {hour} {minute}", "%B %d %Y %H %M")
    except ValueError:
        return None
    return local.replace(tzinfo=timezone(timedelta(hours=offset))).astimezone(timezone.utc)


# ---- cone of uncertainty -----------------------------------------------------

def parse_cone_kmz(raw: bytes) -> dict | None:
    """NHC track-uncertainty KMZ -> GeoJSON FeatureCollection of cone polygons.

    Each polygon is the area swept by circles sized so two-thirds of the last
    five years of NHC official track errors fall inside; NHC quotes roughly
    60-70% of full tracks staying within the 5-day cone. Advisories may carry
    both a short-range and a 5-day cone, so all polygons are returned tagged
    with their forecast period.
    """
    root = _read_kml(raw)
    if root is None:
        return None

    features = []
    for placemark in _iter_local(root, "Placemark"):
        meta = _extended_data(placemark)
        for polygon in _iter_local(placemark, "Polygon"):
            rings = [
                _coords(c.text)
                for outer in _iter_local(polygon, "outerBoundaryIs")
                for c in _iter_local(outer, "coordinates")
            ]
            ring = next((r for r in rings if len(r) >= 4), None)
            if ring is None:
                continue
            ring = _simplify(ring)
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            period = meta.get("fcstpd")
            features.append({
                "type": "Feature",
                "properties": {
                    "forecast_period_hours": int(period) if (period or "").isdigit() else None,
                    "advisory_num": meta.get("advisoryNum"),
                    "storm_type": meta.get("stormType"),
                    "advisory_date": meta.get("advisoryDate"),
                },
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            })

    if not features:
        return None
    # Largest period first so the frontend can draw wide cones beneath narrow ones.
    features.sort(key=lambda f: f["properties"]["forecast_period_hours"] or 0, reverse=True)
    return {"type": "FeatureCollection", "features": features}


# ---- official forecast track -------------------------------------------------

def parse_track_kmz(raw: bytes) -> dict | None:
    """NHC forecast-track KMZ -> forecast points, track polyline, and advisory meta.

    Point placemarks carry the intensity forecast at each projection hour; the
    `x`-prefixed icon styles flag points NHC expects to be post-tropical.
    """
    root = _read_kml(raw)
    if root is None:
        return None

    points: list[dict] = []
    lines: list[tuple[int, list[list[float]]]] = []
    meta: dict[str, str] = {}

    for placemark in _iter_local(root, "Placemark"):
        extended = _extended_data(placemark)
        style = next((s.text or "" for s in _iter_local(placemark, "styleUrl")), "")

        for line in _iter_local(placemark, "LineString"):
            coords = [_coords(c.text) for c in _iter_local(line, "coordinates")]
            path = next((c for c in coords if len(c) >= 2), None)
            if path:
                period = extended.get("fcstpd", "0")
                lines.append((int(period) if period.isdigit() else 0, path))
                meta.update(extended)

        point_coords = [
            _coords(c.text)
            for pt in _iter_local(placemark, "Point")
            for c in _iter_local(pt, "coordinates")
        ]
        position = next((c[0] for c in point_coords if c), None)
        if position is None:
            continue

        cells = _cdata_cells(placemark)
        blob = " ".join(cells)
        hour_match = _HOUR_RE.search(blob)
        is_initial = hour_match is None
        wind = _WIND_RE.search(blob)
        gust = _GUST_RE.search(blob)
        wind_kt = float(wind.group(1)) if wind else None
        gust_kt = float(gust.group(1)) if gust else None
        # Hollow ("x") icons and the low icon mark post-tropical projections.
        post_tropical = bool(re.search(r"#(x[a-z]_point|l_point)", style, re.I))
        valid = next((_parse_valid_at(c) for c in cells if "Valid at" in c), None)

        points.append({
            "fcst_hour": 0 if is_initial else int(hour_match.group(1)),
            "label": "Current" if is_initial else f"{hour_match.group(1)} h",
            "valid_time": iso(valid) if valid else None,
            "lat": position[1],
            "lon": position[0],
            "wind_kt": wind_kt,
            "wind_mph": kt_to_mph(wind_kt),
            "gust_kt": gust_kt,
            "gust_mph": kt_to_mph(gust_kt),
            "post_tropical": post_tropical,
            "stage": stage_code(wind_kt, post_tropical),
            "category": saffir_simpson(wind_kt) if not post_tropical else None,
            "intensity_label": intensity_label(wind_kt, post_tropical),
        })

    if not points and not lines:
        return None
    points.sort(key=lambda p: p["fcst_hour"])
    # Advisories publish nested 72 h and 120 h polylines; keep the longest.
    path = max(lines, key=lambda item: (item[0], len(item[1])))[1] if lines else [
        [p["lon"], p["lat"]] for p in points
    ]

    return {
        "advisory_num": meta.get("advisoryNum"),
        "advisory_local_time": meta.get("pubAdvTime"),
        "forecast_period_hours": max((h for h, _ in lines), default=None) or None,
        "movement_compass": meta.get("stormMovement"),
        "points": points,
        "line": {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"advisory_num": meta.get("advisoryNum")},
                "geometry": {"type": "LineString", "coordinates": path},
            }],
        },
    }


# ---- forecast advisory text (wind radii) -------------------------------------

_PRE_RE = re.compile(r"<pre>(.*?)</pre>", re.S | re.I)
_RADII_RE = re.compile(
    r"^\s*(34|50|64) KT\.+\s*(\d+)NE\s+(\d+)SE\s+(\d+)SW\s+(\d+)NW", re.M)
# Atlantic advisories quote seas in feet, the Pacific ones in metres.
_SEAS_RE = re.compile(
    r"^\s*(\d+)\s*(FT|M) SEAS\.+\s*(\d+)NE\s+(\d+)SE\s+(\d+)SW\s+(\d+)NW", re.M)
_ISSUED_RE = re.compile(r"^\s*(\d{2})(\d{2}) UTC \w{3} (\w{3}) (\d{1,2}) (\d{4})", re.M)
_FCST_BLOCK_RE = re.compile(
    r"^(?:FORECAST VALID|OUTLOOK VALID)\s+(\d{2})/(\d{2})(\d{2})Z\s*(.*?)$", re.M)
_FCST_POSITION_RE = re.compile(r"([\d.]+)([NS])\s+([\d.]+)([EW])")
_ADV_WIND_RE = re.compile(r"MAX(?:IMUM SUSTAINED)? WINDS?\s+(\d+)\s*KT", re.I)
_ADV_GUST_RE = re.compile(r"GUSTS?\s+(?:TO\s+)?(\d+)\s*KT", re.I)

_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def advisory_text(raw_html: str) -> str:
    """Strip the NHC page wrapper down to the fixed-format advisory body."""
    match = _PRE_RE.search(raw_html)
    body = match.group(1) if match else raw_html
    body = re.sub(r"<[^>]+>", "", body)
    return html.unescape(body).strip("\n \t")


def _radii(block: str) -> dict[str, dict[str, int]]:
    """Quadrant radii in nautical miles, keyed by wind threshold."""
    out: dict[str, dict[str, int]] = {}
    for kt, ne, se, sw, nw in _RADII_RE.findall(block):
        out[kt] = {"ne": int(ne), "se": int(se), "sw": int(sw), "nw": int(nw)}
    return out


def _seas(block: str) -> dict | None:
    """Extent of the high-seas threshold, normalised to feet across basins."""
    match = _SEAS_RE.search(block)
    if not match:
        return None
    threshold, unit, ne, se, sw, nw = match.groups()
    value = int(threshold)
    return {
        "threshold": value,
        "unit": unit.lower(),
        "threshold_ft": value if unit.upper() == "FT" else round(value * 3.28084),
        "ne": int(ne), "se": int(se), "sw": int(sw), "nw": int(nw),
    }


def _resolve_day_hour(day: int, hour: int, minute: int, reference: datetime) -> datetime:
    """`DD/HHMMZ` -> full UTC datetime, rolling the month over when needed."""
    year, month = reference.year, reference.month
    if day < reference.day - 15:  # advisory crossed into the next month
        month += 1
        if month > 12:
            month, year = 1, year + 1
    try:
        return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    except ValueError:
        return reference


def parse_forecast_advisory(raw_html: str) -> dict | None:
    """Parse the TCM forecast/advisory: wind radii now and at each projection.

    Radii are the largest extent of that wind anywhere in the quadrant, which
    is what makes them a usable proxy for how large the storm's wind field is
    versus how strong its core is.
    """
    text = advisory_text(raw_html)
    if "FORECAST/ADVISORY" not in text.upper():
        return None

    issued_match = _ISSUED_RE.search(text)
    if issued_match:
        hh, mm, mon, day, year = issued_match.groups()
        month = _MONTHS.index(mon.upper()) + 1 if mon.upper() in _MONTHS else 1
        issued = datetime(int(year), month, int(day), int(hh), int(mm), tzinfo=timezone.utc)
    else:
        issued = datetime.now(timezone.utc)

    # Projection hours run from the synoptic base time, not from issuance: an
    # advisory released at 15Z still labels its 00Z point "12 HR". Anchoring on
    # issuance would report it as 9 h and disagree with the track product.
    synoptic = issued.replace(hour=issued.hour // 6 * 6, minute=0, second=0, microsecond=0)

    blocks = list(_FCST_BLOCK_RE.finditer(text))
    head = text[: blocks[0].start()] if blocks else text

    forecasts = []
    for i, match in enumerate(blocks):
        day, hour, minute, tail = match.groups()
        body = text[match.end(): blocks[i + 1].start() if i + 1 < len(blocks) else len(text)]
        wind = _ADV_WIND_RE.search(body)
        gust = _ADV_GUST_RE.search(body)
        position = _FCST_POSITION_RE.search(tail)
        lat = lon = None
        if position:
            lat = float(position.group(1)) * (-1 if position.group(2) == "S" else 1)
            lon = float(position.group(3)) * (-1 if position.group(4) == "W" else 1)
        note = tail.split("...", 1)[1].strip() if "..." in tail else ""
        valid = _resolve_day_hour(int(day), int(hour), int(minute), issued)
        forecasts.append({
            "valid_time": iso(valid),
            "fcst_hour": round((valid - synoptic).total_seconds() / 3600),
            "lat": lat,
            "lon": lon,
            "note": note,
            "wind_kt": float(wind.group(1)) if wind else None,
            "gust_kt": float(gust.group(1)) if gust else None,
            "radii_nm": _radii(body),
        })

    return {
        "issued": iso(issued),
        "synoptic_time": iso(synoptic),
        "forecaster": (re.search(r"^FORECASTER\s+(.+)$", text, re.M).group(1).strip()
                       if re.search(r"^FORECASTER\s+(.+)$", text, re.M) else None),
        "position_accuracy_nm": (
            int(m.group(1)) if (m := re.search(r"POSITION ACCURATE WITHIN\s+(\d+)\s*NM", text)) else None),
        "initial_radii_nm": _radii(head),
        "seas_nm": _seas(head),
        "forecasts": forecasts,
        "text": text,
    }


def parse_discussion(raw_html: str) -> dict | None:
    """The forecaster's own reasoning, split into discussion and key messages."""
    text = advisory_text(raw_html)
    if not text or "DISCUSSION" not in text.upper():
        return None
    # Drop the WMO header block that precedes the human-written prose.
    body = re.split(r"^\s*\d{3,4} (?:AM|PM) [A-Z]{2,4} .*$", text, maxsplit=1, flags=re.M)
    prose = (body[1] if len(body) > 1 else text).strip()
    prose = re.sub(r"\n\s*\$\$.*$", "", prose, flags=re.S).strip()
    key_messages = None
    if match := re.search(r"^\s*Key Messages:\s*(.+)$", prose, re.S | re.I):
        key_messages = match.group(1).strip()
        prose = prose[: match.start()].strip()
    return {"discussion": prose, "key_messages": key_messages}
