"""Print a gridded field as ASCII so land masking and gradients are visible."""
from __future__ import annotations

import sys
import urllib.request
import json

BASE = "http://127.0.0.1:8000"


def show(data: dict, key: str, fmt) -> None:
    lats = data["lats"]
    lons = data["lons"]
    grid = data["fields"][key]
    print(f"\n=== {key}  (rows north->south, cols west->east)")
    header = "      " + "".join(f"{lon:>6.0f}" for lon in lons)
    print(header)
    for i in range(len(lats) - 1, -1, -1):
        row = "".join("     ." if v is None else fmt(v) for v in grid[i])
        print(f"{lats[i]:>5.1f} {row}")


def main() -> int:
    storm = sys.argv[1] if len(sys.argv) > 1 else "al052026"
    hour = sys.argv[2] if len(sys.argv) > 2 else "0"
    url = f"{BASE}/api/tropical/{storm}/fields?hour={hour}"
    with urllib.request.urlopen(url, timeout=180) as resp:
        data = json.load(resp)

    print(f"{storm} hour={hour} centre={data['centre']} grid="
          f"{len(data['lats'])}x{len(data['lons'])} step={data['step_deg']}")
    show(data, "sst_c", lambda v: f"{v:>6.1f}")
    show(data, "favourability", lambda v: f"{v:>6.0f}")
    show(data, "shear_kt", lambda v: f"{v:>6.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
