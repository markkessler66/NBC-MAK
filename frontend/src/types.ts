export interface ObservationData {
  station: string;
  obs_time: string;
  fetched_at: string;
  description: string;
  temp_f: number | null;
  feels_like_f: number | null;
  dewpoint_f: number | null;
  rh: number | null;
  wind_mph: number | null;
  wind_dir_deg: number | null;
  gust_mph: number | null;
  pressure_mb: number | null;
  visibility_mi: number | null;
  precip_last_hour_in: number | null;
  cloud_layer: string | null;
}

export interface CurrentPayload {
  observation: ObservationData | null;
  alerts_count: number;
  server_time: string;
}

export interface AlertData {
  id: string;
  event: string;
  severity: string;
  urgency: string;
  headline: string;
  onset: string | null;
  ends: string | null;
  area: string;
  description: string;
  instruction: string;
}

export type VarSeries = Record<string, (number | null)[]>;

export interface ModelSeries {
  key: string;
  label: string;
  is_ai: boolean;
  fetched_at: string;
  init_time?: string | null;
  source?: string;
  values: VarSeries;
}

export interface ConsensusVar {
  median: (number | null)[];
  min: (number | null)[];
  max: (number | null)[];
  spread: (number | null)[];
  count: number[];
}

export interface EnsembleData {
  label: string;
  members: number;
  fetched_at: string;
  percentiles: Record<string, Record<string, (number | null)[]>>;
}

export interface DailySummary {
  date: string;
  hi: number;
  lo: number;
  pop: number | null;
  precip_in: number | null;
  temp_spread_max: number | null;
  conditions: string;
  confidence: string;
}

export interface ForecastPayload {
  generated_at: string;
  location: { name: string; lat: number; lon: number };
  timeline: string[];
  models: Record<string, ModelSeries>;
  consensus: Record<string, ConsensusVar>;
  confidence_temp: string[];
  ensemble: EnsembleData | null;
  daily: DailySummary[];
}

export interface GeoJsonFeatureCollection<G = unknown> {
  type: "FeatureCollection";
  features: { type: "Feature"; properties: Record<string, unknown>; geometry: G }[];
}

export type ConePolygons = GeoJsonFeatureCollection<{
  type: "Polygon";
  coordinates: [number, number][][];
}>;

export type TrackLine = GeoJsonFeatureCollection<{
  type: "LineString";
  coordinates: [number, number][];
}>;

export interface TrackPoint {
  fcst_hour: number;
  label: string;
  valid_time: string | null;
  lat: number;
  lon: number;
  wind_kt: number | null;
  wind_mph: number | null;
  gust_kt: number | null;
  gust_mph: number | null;
  post_tropical: boolean;
  stage: string;
  category: number | null;
  intensity_label: string;
}

export interface StormTrack {
  advisory_num: string | null;
  advisory_local_time: string | null;
  forecast_period_hours: number | null;
  movement_compass: string | null;
  points: TrackPoint[];
  line: TrackLine;
}

export interface StormData {
  id: string;
  bin: string;
  name: string;
  classification: string;
  classification_label: string;
  basin: string;
  lat: number;
  lon: number;
  intensity_kt: number | null;
  intensity_mph: number | null;
  category: number | null;
  pressure_mb: number | null;
  movement_dir_deg: number | null;
  movement_speed_kt: number | null;
  movement_speed_mph: number | null;
  last_update: string;
  advisory_num: string | null;
  advisory_url: string | null;
  advisory_issued: string | null;
  forecast_advisory_url: string | null;
  discussion_url: string | null;
  wind_probabilities_url: string | null;
  graphics_url: string | null;
  cone: ConePolygons | null;
  track: StormTrack | null;
}

export interface TropicalPayload {
  fetched_at: string;
  storms: StormData[];
  atlantic_count: number;
  outlooks: { basin: string; label: string; image: string; link: string }[];
}

/** Threshold-classified environmental parameter with its reasoning. */
export interface Metric {
  key: string;
  label: string;
  value: number | null;
  display: string;
  category: string | null;
  tone: "good" | "warn" | "bad" | "neutral";
  note: string;
  score: number | null;
}

export interface LayerFlow {
  speed_kt: number | null;
  from_deg: number | null;
  toward_deg: number | null;
  toward_compass: string | null;
}

export interface EnvironmentPoint {
  fcst_hour: number;
  lat: number;
  lon: number;
  valid_time: string;
  nhc_wind_kt: number | null;
  nhc_stage?: string;
  shear: { magnitude_kt: number; toward_deg: number; toward_compass: string } | null;
  steering: LayerFlow | null;
  flow: Record<"850" | "500" | "200", LayerFlow>;
  sst_c: number | null;
  sst_f: number | null;
  over_land: boolean;
  rh_700_pct: number | null;
  rh_500_pct: number | null;
  outflow_temp_c: number | null;
  temp_850_c: number | null;
  environmental_pressure_mb: number | null;
  model_central_pressure_mb: number | null;
  model_pressure_deficit_mb: number | null;
  height_500_m: number | null;
  height_500_gradient: {
    toward_higher_deg: number;
    toward_higher_compass: string;
    per_1000km: number;
  } | null;
  wave_height_m: number | null;
}

export interface PatternFeature {
  lat: number;
  lon: number;
  pressure_mb: number | null;
  height_500_m: number | null;
  distance_km: number;
  bearing_deg: number;
  bearing_compass: string;
  on_edge: boolean;
}

export interface StormEnvironment {
  computed_at: string;
  source: string;
  method: string;
  ring_radius_km: number;
  current: EnvironmentPoint;
  along_track: EnvironmentPoint[];
  pattern: {
    grid_step_deg: number;
    grid_extent_km: number;
    exclusion_km: number;
    surface_high: PatternFeature | null;
    mid_ridge: PatternFeature | null;
    mid_trough: PatternFeature | null;
    surface_low: PatternFeature | null;
    samples: PatternFeature[];
  } | null;
}

export type Quadrants = { ne: number; se: number; sw: number; nw: number };

export interface AdvisoryForecast {
  valid_time: string;
  fcst_hour: number;
  lat: number | null;
  lon: number | null;
  note: string;
  wind_kt: number | null;
  gust_kt: number | null;
  radii_nm: Record<string, Quadrants>;
}

export interface StormFieldsPayload {
  storm_id: string;
  fcst_hour: number;
  lead_hours: number[];
  note: string;
  /** Set when the upstream model feed is over quota; the grid fields are absent. */
  unavailable?: string;
  /** Set when only the cached ocean grid could be served; atmosphere layers are empty. */
  degraded?: string | null;
  valid_time?: string;
  centre?: { lat: number; lon: number };
  lats?: number[];
  lons?: number[];
  bounds?: { west: number; east: number; south: number; north: number };
  step_deg?: number;
  fields?: Record<string, (number | null)[][]>;
  source?: string;
}

export interface ScenarioAdjustments {
  shear_delta_kt: number;
  sst_delta_c: number;
  rh_delta_pct: number;
  ridge_factor: number;
}

export interface ScenarioPoint {
  fcst_hour: number;
  valid_time: string | null;
  nhc_wind_kt: number | null;
  nhc_lat: number;
  nhc_lon: number;
  baseline_wind_kt: number | null;
  scenario_wind_kt: number | null;
  model_wind_kt: number | null;
  scenario_lat: number | null;
  scenario_lon: number | null;
  shift_km: number | null;
  shift_compass: string | null;
  sst_c: number | null;
  shear_kt: number | null;
  rh_700_pct: number | null;
}

export interface ScenarioPayload {
  available: boolean;
  reason?: string;
  adjustments: ScenarioAdjustments;
  limits?: Record<keyof ScenarioAdjustments, { min: number; max: number }>;
  points?: ScenarioPoint[];
  summary?: string;
  changed?: boolean;
  method?: string;
  caveat?: string;
}

export interface StormDetailPayload {
  storm: StormData;
  fetched_at: string;
  advisory: {
    issued: string;
    synoptic_time: string;
    forecaster: string | null;
    position_accuracy_nm: number | null;
    initial_radii_nm: Record<string, Quadrants>;
    seas_nm: ({ threshold: number; unit: string; threshold_ft: number } & Quadrants) | null;
    forecasts: AdvisoryForecast[];
    text: string;
  } | null;
  discussion: { discussion: string; key_messages: string | null } | null;
  wind_field: {
    radii: Record<string, { quadrants_nm: Quadrants; max_nm: number; mean_nm: number; mean_km: number }>;
    size_class: string | null;
    note: string;
  } | null;
  environment: StormEnvironment;
  diagnostics: {
    headline: string;
    intensity: {
      score: number | null;
      verdict: string;
      tone: Metric["tone"];
      limiter: string | null;
      metrics: Metric[];
      narrative: string;
    };
    steering: {
      reference_layer: string;
      agreement_deg: number | null;
      geometry: {
        initial_heading_deg?: number;
        final_heading_deg?: number;
        turn_deg?: number;
        mean_speed_kt?: number | null;
        total_distance_km?: number;
      };
      metrics: Metric[];
      narrative: string;
    };
    caveat: string;
  };
}

export interface BucketStats {
  n: number;
  mae: number;
  rmse: number;
  bias: number;
}

export interface VerificationPayload {
  variable: string;
  window_days: number;
  computed_at: string;
  bucket_order: string[];
  models: Record<
    string,
    { label: string; buckets: Record<string, BucketStats>; overall: BucketStats | null }
  >;
  best_by_bucket: Record<string, string>;
  sample_note: string;
}

export interface SourceStatusData {
  source: string;
  label: string;
  ok: boolean;
  fetched_at: string | null;
  age_seconds: number | null;
  duration_ms: number | null;
  message: string;
  items: number | null;
  extra?: {
    cycle?: string;
    files?: number;
    bytes?: number;
    init_to_ingest_min?: number;
    [key: string]: unknown;
  };
}

export interface StatusPayload {
  server_time: string;
  sources: SourceStatusData[];
  archive: {
    forecast_rows: number;
    observation_rows: number;
    distinct_runs: number;
    archiving_since: string | null;
    recent_events: {
      source: string;
      started_at: string;
      duration_ms: number;
      ok: boolean;
      message: string;
      items: number;
    }[];
  };
}

export interface MetaPayload {
  app: string;
  phase: number;
  location: { name: string; lat: number; lon: number; tz: string };
  models: { key: string; label: string; source: string; is_ai: boolean; days: number; note: string }[];
}
