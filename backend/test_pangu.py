"""One-shot manual test of local Pangu-Weather inference (run from backend/)."""
import asyncio
import json

from app.http_client import close_client
from app.models_ai import pangu


async def main():
    cycle = await pangu.find_latest_ic_cycle()
    print("IC cycle:", cycle)
    series = await pangu.run_forecast(steps=7)
    meta = series.pop("ingest_meta")
    print("bench:", json.dumps(meta, indent=2))
    print("times:", series["times"])
    for var, vals in series["values"].items():
        print(f"{var}: {vals}")
    await close_client()


if __name__ == "__main__":
    asyncio.run(main())
