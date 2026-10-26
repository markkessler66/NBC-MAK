"""One-shot manual test of native NOAA ingestion (run from backend/)."""
import asyncio
import json
import sys

from app.ingest import noaa
from app.http_client import close_client


async def main(key: str):
    model = noaa.NATIVE_MODELS[key]
    cycle = await noaa.find_latest_complete_cycle(model)
    print(f"latest complete {key} cycle: {cycle}")
    series = await noaa.ingest_native(key)
    if series is None:
        print("cycle already ingested (Zarr exists)")
        return
    meta = series.pop("ingest_meta")
    print("ingest_meta:", json.dumps(meta, indent=2))
    print("init_time:", series["init_time"])
    print("hours:", len(series["times"]), "first:", series["times"][0], "last:", series["times"][-1])
    print("variables:", sorted(series["values"].keys()))
    row = {k: v[2] for k, v in series["values"].items()}
    print(f"sample @ {series['times'][2]}:", json.dumps(row, indent=2))
    await close_client()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "hrrr"))
