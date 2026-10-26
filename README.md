# Personal Weather Lab

A self-hosted weather intelligence and forecasting platform for the Dallas–Fort Worth area,
built to the *Personal Weather Intelligence & Forecasting System* spec. Covers **Phase 1**
(DFW dashboard), **Phase 2** (native NOAA GRIB2 ingestion + Zarr grid archive), **Phase 3**
(verification with a year of backfilled history), and the first **Phase 4** milestone —
Pangu-Weather running locally on the RTX 5070 Ti. The forecast archive accumulates
continuously via an always-on Windows scheduled task.

## What it does today

- **Live DFW dashboard** — current conditions from the nearest NWS/ASOS station, active NWS
  alerts, NEXRAD composite radar on an interactive map, and a 10-day consensus outlook.
- **Multi-model forecast comparison** — HRRR, GFS, ECMWF IFS, ECMWF AIFS (AI), NWS NBM, and
  the official NWS gridpoint forecast, side by side on one chart and in a per-hour comparison
  table with a time slider.
- **Uncertainty, always** — the system forecast is the multi-model median, displayed with the
  full model range, spread, a GEFS 31-member ensemble band, and a lead-time-aware confidence
  label. Model disagreement is exposed, never averaged away.
- **Forecast verification** — every model refresh archives point forecasts; every observation
  is archived. MAE / RMSE / bias per model and lead-time bucket (1 h → 7 d), benchmarked
  against a persistence baseline. A one-time backfill (`backend/backfill.py`) seeded a full
  year of history: ~15k KADS observations (IEM ASOS archive) and ~130k lagged model forecasts
  (Open-Meteo Previous Runs API, flagged `origin='backfill'` with day-granular leads) — so
  model rankings are statistically meaningful from day one, and Phase 5 has a training set.
- **Local GPU AI model (Phase 4)** — Pangu-Weather's 24 h ONNX model runs on the RTX 5070 Ti
  via ONNX Runtime CUDA, initialized from each new GFS analysis (global fields fetched by
  S3 byte-range). Seven autoregressive steps ≈ 3 minutes at ~28 s/step using ~15.9 GB VRAM;
  the DFW point series joins the comparison table, consensus, and verification as
  "Pangu (local)" with daily resolution.
- **Native NOAA ingestion (Phase 2)** — HRRR and GFS are pulled directly from NOAA: S3
  probing finds the newest complete cycle (true initialization time), then the NOMADS GRIB
  filter delivers variable- and region-subsetted GRIB2 (~0.1–1.5 MB per forecast hour for
  the North Texas box). Grids are decoded with cfgrib/ecCodes and archived to Zarr under
  `backend/data/grids/`; the home-point series feeds the dashboard and verification keyed
  by real run times. Any failure falls back to Open-Meteo automatically.
- **Tropical watch** — NHC active storms on a basin map with official **cones of uncertainty**
  and forecast tracks (parsed from NHC's cone/track KMZ), plus the 2-day/7-day Atlantic
  graphical outlooks (proxied — NHC blocks hotlinks).
- **Per-storm analysis** — click any system for a full workup: what is driving its **strength**
  (SST, deep-layer shear, mid-level humidity, outflow temperature) and its **direction**
  (deep-layer mean steering flow, 500 hPa height gradient, ridge/trough positions), each
  sampled along the official forecast track and explained in plain language. Includes the
  quadrant wind field, seas radii, and the raw NHC forecast advisory and discussion.
- **Environment map layers** — the same variables as shaded overlays on the storm map, chosen
  from a dropdown and steppable through every official forecast hour: development potential,
  SST, deep-layer shear, mid-level humidity, MSLP, and 500 hPa heights. The palette is
  consistent throughout — **red is whatever favours intensification, blue whatever suppresses
  it** — so warm water and *slack* shear both read red. Land is masked rather than
  interpolated across.
- **What-if sandbox** — sliders perturb the observed environment (shear, SST, mid-level
  humidity, steering-ridge strength) and re-run a toy intensity/track model, then apply the
  *difference* to NHC's official forecast. Answers "the shear is forecast high, but what if it
  backs off 15 kt?" or "what if the ridge weakens and the track bends right?" with a revised
  intensity curve and a displaced track drawn beside the official one. Anchored to NHC by
  construction: with every slider neutral the output is NHC's forecast exactly.
- **System status page** — per-source ingest health, data age, latency, model run ("HRRR run
  16Z, ingested +135 min after init"), and the audit log. Data freshness is a first-class
  feature.

## Architecture

```
NWS API ─┐                                  ┌─ /api/current      ┐
Open-Meteo (HRRR/GFS/IFS/AIFS/NBM/GEFS) ─┤→ async ingestion loops │→ /api/forecast     │→ React dashboard
NHC CurrentStorms ─┘      (error-isolated, per-source status)     ├─ /api/verification │   (Vite + Tailwind +
                              │                                   ├─ /api/tropical     │    ECharts + MapLibre)
                              ▼                                   └─ /api/status      ┘
              SQLite archive (forecasts, observations,
              ingest events) — swappable to PostgreSQL
```

- `backend/` — Python 3.12+ / FastAPI / httpx / SQLAlchemy. Each data source runs on its own
  asyncio loop; one source failing never takes down the rest.
- `frontend/` — React 19 + TypeScript + Vite + Tailwind, ECharts for time series, MapLibre GL
  for radar/tropical maps.
- Point forecasts are stored per `(model, run_hour, target_time)` with lead time, enabling the
  verification queries the spec treats as more important than the UI.

## Running it

### Always-on service (already configured)

The backend runs as the **"Personal Weather Lab"** Windows scheduled task: it starts at
logon, restarts uvicorn automatically if it exits, and logs to `backend/data/server.log`.
Manage it with `Start-ScheduledTask`/`Stop-ScheduledTask -TaskName "Personal Weather Lab"`
or Task Scheduler. The UI is served at `http://127.0.0.1:8000`.

### Desktop shortcut

A **Personal Weather Lab** shortcut on the desktop opens the dashboard in its own
chrome-less browser window. It runs `scripts/start-weather-lab.ps1`, which checks the backend
is answering, starts the scheduled task (or `backend/run_server.ps1` if the task is missing)
and waits for it when it is not, and reports failures in a message box. Recreate the shortcut
— on this machine or a new one — with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-desktop-shortcut.ps1
```

### Manual run (development)

Backend (terminal 1) — **requires Python 3.13** (ecCodes ships Windows wheels for ≤3.13):

```powershell
cd backend
py -3.13 -m venv .venv                # first time only
.\.venv\Scripts\pip install -r requirements.txt   # first time only
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Frontend dev server (terminal 2):

```powershell
cd frontend
npm install                            # first time only
npm run dev                            # → http://localhost:5173
```

Or build once (`npm run build`) and let the backend serve the UI itself at
`http://127.0.0.1:8000` — the backend mounts `frontend/dist` automatically when it exists.

### Docker

```bash
docker compose up --build              # → http://localhost:8000
```

## Configuration

Environment variables (prefix `WLAB_`, or put them in `backend/.env`):

| Variable | Default | Purpose |
|---|---|---|
| `WLAB_HOME_NAME` | `Frisco, TX` | Display name |
| `WLAB_HOME_LAT` / `WLAB_HOME_LON` | `33.1507` / `-96.8236` | Forecast point |
| `WLAB_DB_URL` | `sqlite:///./data/weatherlab.db` | Swap in PostgreSQL here |
| `WLAB_NATIVE_INGEST` | `true` | Native NOAA GRIB ingestion for HRRR/GFS |
| `WLAB_GRID_RETENTION_DAYS` | `14` | How long Zarr grid runs are kept |
| `WLAB_POLL_NATIVE` | `600` | New-cycle check interval, seconds (cheap S3 HEAD) |
| `WLAB_POLL_MODELS` | `3600` | API-feed model refresh seconds (see `config.py` for the rest) |
| `WLAB_POLL_TROPICAL_DETAIL` | `10800` | Per-storm environment sampling interval, seconds (see the quota note below) |
| `VITE_CARTO_KEY` | — | CARTO basemap key (put in `frontend/.env`; see `.env.example`) |

Models are registered in `backend/app/config.py` (`MODELS`) — adding another Open-Meteo model
is a one-line change.

## Data sources

| Source | Data | Cadence |
|---|---|---|
| NWS API (`api.weather.gov`) | Observations, gridpoint forecast, alerts | 5 min / 30 min / 5 min |
| NOAA S3 + NOMADS GRIB filter | HRRR (hourly runs, f00–f18) and GFS (4×/day, f000–f240) native GRIB2, subset to North Texas | new-cycle check every 10 min |
| Open-Meteo | ECMWF IFS, ECMWF AIFS, NBM point forecasts (+ HRRR/GFS fallback) | 60 min |
| Open-Meteo Ensemble | GEFS 31-member percentiles | 2 h |
| NHC `CurrentStorms.json` | Active tropical systems | 30 min |
| NHC cone/track KMZ + text products | Cones of uncertainty, forecast track points, wind/seas radii, forecast advisory and discussion | 30 min (with the storm feed) |
| Open-Meteo GFS + Marine | Per-storm environment: 850/500/200 hPa winds, 700/500 hPa humidity, MSLP and 500 hPa heights, SST — as ring samples along the track and as a gridded cube for the map layers | 3 h per active system |
| Iowa Environmental Mesonet | NEXRAD composite radar tiles | 5 min (map tiles) |

### Staying inside the Open-Meteo quota

Open-Meteo's free tier bills **per sampled location, not per request**, and enforces four
ceilings at once (minute, hour, day, month). The tropical map layers are the only part of the
system that samples hundreds of locations at a time, so they are the part that can starve
everything else — including the dashboard models — if left unchecked.

- **One cube per storm.** A single request returns the *whole hourly series* for each
  location, so the grid is sampled once over the entire forecast track and sliced per lead
  hour. Stepping through lead times in the UI is then free. Sampling per lead hour instead
  cost ~20× more for identical output.
- **SST is cached separately** on a coarser mesh and bilinearly interpolated onto the
  atmospheric grid: it is a slowly varying boundary condition, so one sample serves a whole
  five-day forecast.
- **A shared token bucket** (`tropical_env`) meters every Open-Meteo caller against all
  ceilings. Short waits are absorbed; anything longer fails fast.
- **Upstream 429s are believed over local accounting.** Our counters reset when the process
  restarts and Open-Meteo's do not, so a refusal pauses that budget until the real rollover
  (midnight UTC for the daily cap) rather than letting a drained bucket dribble tokens back
  and turn every later request into a multi-minute stall.
- **Degradation is partial and visible.** If the atmosphere cannot be fetched but the ocean
  grid is cached, the SST layer still renders and the UI says why the others are blank.
  Remaining headroom is reported at `/api/status` under `api_budget`.

## Roadmap (per spec)

- [x] **Phase 1** — DFW dashboard: observations, HRRR/GFS/ECMWF/NWS, charts, map, timestamps
- [x] **Phase 2** — native NOAA GRIB2 ingestion (HRRR/GFS with true init times), Zarr grid
      archive with retention, automatic polling, per-source status, historical point archive
      (ECMWF IFS/AIFS remain API-fed pending native open-data GRIB handling)
- [x] **Phase 3 (partial)** — forecast/observation archiving + MAE/RMSE/bias by lead time vs
      a persistence baseline (calibration & skill scores still to come)
- [x] **Phase 4 (first milestone)** — Pangu-Weather 24 h on the RTX 5070 Ti (CUDA), fully
      benchmarked and integrated. Next: the 6 h model for sub-daily resolution; GraphCast
      needs JAX (WSL2) and is deferred.
- [ ] **Phase 5** — DFW ML post-processing (learn model errors: XGBoost/LightGBM first).
      Training data ready: a year of backfilled (forecast, observation) pairs.
- [x] **Phase 6–7 (partial)** — hurricane tracker: forecast tracks, cones of uncertainty, wind
      and seas radii, per-storm environmental diagnostics (shear/SST/steering) with
      plain-language reasoning, shaded environment map layers, and a what-if sensitivity
      sandbox (multi-model track comparison still to come)
- [ ] **Phase 8** — WRF/MPAS regional NWP feasibility on local hardware
- [ ] **Phase 9** — radar nowcasting
- [ ] **Phase 10** — alerting + fully autonomous forecast cycle

## Scientific integrity notes

- The consensus is a transparent median — no learned weighting is applied until verification
  history justifies it (spec §21).
- Verification compares each archived forecast against hourly-averaged observations at the
  valid time, bucketed by lead time, with a persistence baseline for reference.
- Small-sample cells are flagged; "best model" requires ≥ 20 matched samples.
- Storm shear and steering are **annulus averages** on a ring around the centre, not
  centre-point samples, so the cyclone's own circulation is removed from its environment —
  the same reasoning SHIPS-type diagnostics use. Where GFS cannot resolve a storm's core
  (common for majors at 0.25°), the modelled central pressure is shown against NHC's analysed
  value and flagged rather than quietly reported.
- Intensity favourability is limited by its weakest ingredient: land interaction,
  sub-threshold SST, or extreme shear caps the composite score instead of being averaged
  against favourable factors. The map's "development potential" layer uses the same rule, so
  the shading and the prose cannot disagree.
- The map layers are **raw model fields**, deliberately not annulus averages: near the centre
  they include the model's own vortex, which is how operational shear analyses render them.
  The written diagnostics use the vortex-removed ring values instead, and the UI says so.
- The what-if sandbox is a **toy model, and is labelled as one**. It reports the *difference*
  between a baseline run and a perturbed run, applied to NHC's forecast, so its output is a
  sensitivity — "this ingredient is worth about this much" — not an independent prediction.
  Its baseline is checked against NHC's official intensity curve (currently within roughly
  10–15 kt over five days); the sub-MPI ceiling tapers smoothly rather than cliff-edging at
  26.5 °C, because a mature cyclone carries real inertia over marginal water.
