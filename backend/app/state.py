"""In-memory registry of the latest ingested data.

The API serves from this registry; the database is used for the historical
archive, verification, and the ingest audit log. If one source fails, its
previous snapshot remains available and its status reflects the failure.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SourceStatus:
    source: str
    label: str
    ok: bool = False
    fetched_at: datetime | None = None
    duration_ms: float | None = None
    message: str = "not yet fetched"
    extra: dict = field(default_factory=dict)


@dataclass
class LatestData:
    observation: dict | None = None
    # model key -> {"key","label","fetched_at","times":[iso...],"values":{var:[...]}}
    model_series: dict[str, dict] = field(default_factory=dict)
    ensemble: dict | None = None
    alerts: list[dict] = field(default_factory=list)
    tropical: dict | None = None
    nws_point: dict | None = None
    statuses: dict[str, SourceStatus] = field(default_factory=dict)

    def status(self, source: str, label: str) -> SourceStatus:
        if source not in self.statuses:
            self.statuses[source] = SourceStatus(source=source, label=label)
        return self.statuses[source]


LATEST = LatestData()
