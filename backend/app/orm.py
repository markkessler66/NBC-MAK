"""Database schema: forecast archive, observations, ingest audit log.

Large gridded data (Zarr/GRIB) is out of scope for Phase 1; this schema holds
point forecasts and observations needed for verification, per the spec's
"PostgreSQL for metadata/forecasts/observations/verification" guidance.
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Boolean, UniqueConstraint, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PointForecast(Base):
    """One model's forecast for one target hour at the home point."""
    __tablename__ = "point_forecasts"
    __table_args__ = (
        UniqueConstraint("model", "run_hour", "target_time", name="uq_model_run_target"),
        Index("ix_pf_target", "target_time"),
        Index("ix_pf_model_run", "model", "run_hour"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model: Mapped[str] = mapped_column(String(32))
    # Hour in which this forecast snapshot was fetched (proxy for model run availability).
    run_hour: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    target_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lead_hours: Mapped[float] = mapped_column(Float)
    # 'live' = archived in real time; 'backfill' = reconstructed from lagged
    # historical forecasts (day-granular run attribution).
    origin: Mapped[str] = mapped_column(String(16), default="live", server_default="live")

    temp_f: Mapped[float | None] = mapped_column(Float, nullable=True)
    dewpoint_f: Mapped[float | None] = mapped_column(Float, nullable=True)
    rh: Mapped[float | None] = mapped_column(Float, nullable=True)
    precip_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    precip_in: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_mph: Mapped[float | None] = mapped_column(Float, nullable=True)
    gust_mph: Mapped[float | None] = mapped_column(Float, nullable=True)
    cloud_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    cape: Mapped[float | None] = mapped_column(Float, nullable=True)


class Observation(Base):
    """Surface observation archived for forecast verification."""
    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint("station", "obs_time", name="uq_station_time"),
        Index("ix_obs_hour", "obs_hour"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station: Mapped[str] = mapped_column(String(16))
    obs_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Observation time rounded to the nearest hour; join key for verification.
    obs_hour: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    temp_f: Mapped[float | None] = mapped_column(Float, nullable=True)
    dewpoint_f: Mapped[float | None] = mapped_column(Float, nullable=True)
    rh: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_mph: Mapped[float | None] = mapped_column(Float, nullable=True)
    gust_mph: Mapped[float | None] = mapped_column(Float, nullable=True)
    pressure_mb: Mapped[float | None] = mapped_column(Float, nullable=True)


class IngestEvent(Base):
    """Audit log of every ingestion attempt (latency + success tracking)."""
    __tablename__ = "ingest_events"
    __table_args__ = (Index("ix_ie_source_started", "source", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(48))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float] = mapped_column(Float)
    ok: Mapped[bool] = mapped_column(Boolean)
    message: Mapped[str] = mapped_column(String(500), default="")
    items: Mapped[int] = mapped_column(Integer, default=0)
