"""Quick archive inspection: run hours per model (run from backend/)."""
from sqlalchemy import text

from app.db import session_scope

with session_scope() as s:
    rows = s.execute(text(
        "SELECT model, run_hour, COUNT(*) AS n, MAX(lead_hours) AS max_lead "
        "FROM point_forecasts WHERE model IN ('hrrr','gfs') "
        "GROUP BY model, run_hour ORDER BY run_hour DESC LIMIT 8"
    )).all()
    for model, run_hour, n, max_lead in rows:
        print(f"{model:5} run={run_hour} rows={n} max_lead={max_lead}h")
