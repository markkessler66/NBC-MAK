"""Unit conversions for NWS SI observation fields."""


def c_to_f(c: float | None) -> float | None:
    return None if c is None else round(c * 9 / 5 + 32, 1)


def kmh_to_mph(kmh: float | None) -> float | None:
    return None if kmh is None else round(kmh * 0.621371, 1)


def ms_to_mph(ms: float | None) -> float | None:
    return None if ms is None else round(ms * 2.23694, 1)


def pa_to_mb(pa: float | None) -> float | None:
    return None if pa is None else round(pa / 100.0, 1)


def m_to_mi(m: float | None) -> float | None:
    return None if m is None else round(m * 0.000621371, 1)


def mm_to_in(mm: float | None) -> float | None:
    return None if mm is None else round(mm / 25.4, 3)


def kt_to_mph(kt: float | None) -> float | None:
    return None if kt is None else round(kt * 1.15078, 0)
