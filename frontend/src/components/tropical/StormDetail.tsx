import { useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { usePoll } from "../../hooks";
import { ageString, compass, fmtFull, num } from "../../lib/format";
import type { ScenarioPayload, StormDetailPayload, StormFieldsPayload } from "../../types";
import { AlongTrackTable } from "./AlongTrackTable";
import { BasinMap } from "./BasinMap";
import { EnvironmentChart } from "./EnvironmentChart";
import { FieldControls } from "./FieldControls";
import type { FieldKey } from "./fieldScales";
import { MetricGrid } from "./MetricGrid";
import { WhatIf } from "./WhatIf";
import { intensityTag, stormColor, stormTitle, toneStyle } from "./stormStyle";
import { WindField } from "./WindField";

const REFRESH_MS = 5 * 60 * 1000;

function ScoreBar({ score, tone }: { score: number | null; tone: string }) {
  if (score == null) return null;
  const fill = { good: "bg-emerald-400", warn: "bg-amber-400", bad: "bg-rose-400" }[tone] ?? "bg-slate-400";
  return (
    <div className="flex items-center gap-2 min-w-[140px]">
      <div className="h-1.5 flex-1 rounded-full bg-slate-800 overflow-hidden">
        <div className={`h-full rounded-full ${fill}`} style={{ width: `${score}%` }} />
      </div>
      <span className="text-xs font-mono text-slate-400 shrink-0">{score}/100</span>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <span className="stat-label block">{label}</span>
      <span className="font-mono text-sm text-slate-200">{value}</span>
    </div>
  );
}

export function StormDetail({ stormId, onBack }: { stormId: string; onBack: () => void }) {
  const { data, error } = usePoll<StormDetailPayload>(
    () => api.tropicalStorm(stormId),
    REFRESH_MS,
    [stormId],
  );

  const [fieldKey, setFieldKey] = useState<FieldKey | null>("favourability");
  const [fieldHour, setFieldHour] = useState(0);
  const [fields, setFields] = useState<StormFieldsPayload | null>(null);
  const [fieldsLoading, setFieldsLoading] = useState(false);
  const [scenario, setScenario] = useState<ScenarioPayload | null>(null);
  const wantFields = fieldKey !== null;

  // Only draw a displaced track once it actually departs from the official one.
  const scenarioTrack = useMemo<[number, number][] | null>(() => {
    const points = scenario?.points;
    if (!scenario?.available || !scenario.changed || !points) return null;
    const moved = points.some((p) => (p.shift_km ?? 0) >= 15);
    if (!moved) return null;
    return points
      .filter((p) => p.scenario_lat != null && p.scenario_lon != null)
      .map((p) => [p.scenario_lon as number, p.scenario_lat as number]);
  }, [scenario]);

  // One request carries every variable, so changing the overlay is free and
  // only a new storm or lead time goes back to the server.
  useEffect(() => {
    if (!wantFields) return;
    let cancelled = false;
    setFieldsLoading(true);
    api
      .tropicalFields(stormId, fieldHour)
      .then((payload) => !cancelled && setFields(payload))
      .catch(() => !cancelled && setFields(null))
      .finally(() => !cancelled && setFieldsLoading(false));
    return () => {
      cancelled = true;
    };
  }, [stormId, fieldHour, wantFields]);

  const back = (
    <button
      type="button"
      onClick={onBack}
      className="text-xs text-sky-400 hover:text-sky-300 focus:outline-none focus-visible:ring-2
                 focus-visible:ring-sky-500 rounded px-1 -mx-1"
    >
      ← All active systems
    </button>
  );

  if (error && !data) {
    return (
      <div className="space-y-3">
        {back}
        <div className="card p-4 text-sm text-amber-300">Could not load this system: {error}</div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="space-y-3">
        {back}
        <div className="card p-4 text-sm text-slate-500">
          Sampling the storm environment (shear, SST, steering)…
        </div>
      </div>
    );
  }

  const { storm, diagnostics, environment, advisory, discussion, wind_field: windField } = data;
  const { intensity, steering } = diagnostics;
  const color = stormColor(storm.classification);
  const intensityTone = toneStyle(intensity.tone);
  const current = environment.current;
  const track = storm.track;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        {back}
        <span className="text-[11px] text-slate-500 font-mono">
          analysis {ageString(environment.computed_at)}
        </span>
      </div>

      {/* Headline: the one-glance answer to "what is this doing and why". */}
      <div className="card p-4" style={{ borderColor: `${color}44` }}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span
                className="w-3.5 h-3.5 rounded-full shrink-0"
                style={{ background: color, boxShadow: `0 0 12px -1px ${color}` }}
              />
              <h2 className="text-xl font-semibold text-slate-100">{stormTitle(storm)}</h2>
              <span
                className="text-[11px] px-1.5 py-0.5 rounded border font-medium"
                style={{ color, borderColor: `${color}55`, background: `${color}1a` }}
              >
                {intensityTag(storm)}
              </span>
            </div>
            <p className="text-sm text-slate-300 mt-2 max-w-3xl leading-relaxed">
              {diagnostics.headline}
            </p>
          </div>
          <div className="text-right shrink-0">
            <span className={`text-sm font-semibold ${intensityTone.text}`}>{intensity.verdict}</span>
            <div className="mt-1.5">
              <ScoreBar score={intensity.score} tone={intensity.tone} />
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-x-4 gap-y-3 mt-4 pt-4 border-t border-slate-800">
          <Fact
            label="Max sustained"
            value={`${num(storm.intensity_mph, 0, " mph")} / ${num(storm.intensity_kt, 0, " kt")}`}
          />
          <Fact label="Min pressure" value={num(storm.pressure_mb, 0, " mb")} />
          <Fact
            label="Movement"
            value={
              storm.movement_dir_deg != null
                ? `${compass(storm.movement_dir_deg)} ${num(storm.movement_speed_mph, 0, " mph")}`
                : "Stationary"
            }
          />
          <Fact
            label="Position"
            value={`${storm.lat?.toFixed(1)}N ${Math.abs(storm.lon ?? 0).toFixed(1)}W`}
          />
          <Fact label="Basin" value={storm.basin} />
          <Fact label="Advisory" value={`#${storm.advisory_num ?? "—"}`} />
        </div>

        <div className="flex flex-wrap gap-3 mt-3 text-xs">
          {[
            { href: storm.advisory_url, label: "Public advisory" },
            { href: storm.forecast_advisory_url, label: "Forecast advisory" },
            { href: storm.discussion_url, label: "Discussion" },
            { href: storm.wind_probabilities_url, label: "Wind probabilities" },
            { href: storm.graphics_url, label: "NHC graphics" },
          ]
            .filter((l) => l.href)
            .map((l) => (
              <a
                key={l.label}
                href={l.href!}
                target="_blank"
                rel="noreferrer"
                className="text-sky-400 hover:text-sky-300 underline underline-offset-2"
              >
                {l.label} →
              </a>
            ))}
        </div>
      </div>

      {/* Track + cone */}
      <div className="card p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="card-title">Forecast Track & Cone of Uncertainty</div>
          {track?.advisory_local_time && (
            <span className="text-[11px] text-slate-500 font-mono">
              advisory #{track.advisory_num} · {track.advisory_local_time}
            </span>
          )}
        </div>
        <div className="mb-3">
          <FieldControls
            value={fieldKey}
            onChange={setFieldKey}
            hour={fieldHour}
            leadHours={fields?.lead_hours ?? []}
            onHourChange={setFieldHour}
            validTime={fields?.valid_time ?? null}
            loading={fieldsLoading}
            note={fields?.note}
            unavailable={fields?.unavailable ?? null}
            degraded={fields?.degraded ?? null}
          />
        </div>
        <BasinMap
          storms={[storm]}
          focusId={storm.id}
          height="460px"
          fieldGrid={fields}
          fieldKey={fieldKey}
          scenarioTrack={scenarioTrack}
        />
        <p className="text-[11px] text-slate-500 mt-2 leading-relaxed">
          The cone encloses the likely path of the <em>centre</em>: it is drawn from circles sized so
          two-thirds of NHC's track errors over the last five years fall inside, and historically the
          full track stays within the 5-day cone about 60–70% of the time. Impacts routinely extend
          well beyond it. Numbered markers are the official forecast positions in hours ahead.
          {scenarioTrack && (
            <>
              {" "}
              The dashed <span className="text-violet-300">violet</span> line is your what-if track.
            </>
          )}
        </p>
      </div>

      {/* Why it will strengthen or weaken */}
      <div className="card p-4">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <div className="card-title">What Is Driving Intensity</div>
          <span className={`text-[11px] px-2 py-0.5 rounded border ${intensityTone.badge}`}>
            {intensity.verdict}
          </span>
        </div>
        <p className="text-sm text-slate-300 leading-relaxed mb-4 max-w-4xl">
          {intensity.narrative}
        </p>
        <MetricGrid metrics={intensity.metrics} columns={3} />
      </div>

      {/* Why it is going where it is going */}
      <div className="card p-4">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <div className="card-title">What Is Steering It</div>
          <span className="text-[11px] text-slate-500 font-mono">
            compared against {steering.reference_layer}
            {steering.agreement_deg != null && ` · ${steering.agreement_deg}° from observed motion`}
          </span>
        </div>
        <p className="text-sm text-slate-300 leading-relaxed mb-4 max-w-4xl">{steering.narrative}</p>
        <MetricGrid metrics={steering.metrics} columns={3} />
      </div>

      {/* Environment along the official track */}
      <div className="card p-4">
        <div className="card-title mb-1">Environment Along The Forecast Track</div>
        <p className="text-[11px] text-slate-500 mb-3 max-w-4xl leading-relaxed">
          {environment.method}
        </p>
        <EnvironmentChart points={environment.along_track} />
        <div className="mt-4">
          <AlongTrackTable points={environment.along_track} trackPoints={track?.points ?? []} />
        </div>
      </div>

      <WhatIf stormId={storm.id} onScenarioChange={setScenario} />

      {windField && (
        <WindField
          radii={windField.radii}
          sizeClass={windField.size_class}
          note={windField.note}
          seas={advisory?.seas_nm ?? null}
        />
      )}

      {/* Snapshot of the immediate surroundings */}
      <div className="card p-4">
        <div className="card-title mb-3">Current Conditions At The Centre</div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-x-4 gap-y-3">
          <Fact
            label="SST"
            value={current.over_land ? "over land" : `${num(current.sst_c, 1, " °C")} / ${num(current.sst_f, 0, " °F")}`}
          />
          <Fact
            label="Deep-layer shear"
            value={current.shear ? `${num(current.shear.magnitude_kt, 0, " kt")} → ${current.shear.toward_compass}` : "—"}
          />
          <Fact label="RH 700 hPa" value={num(current.rh_700_pct, 0, "%")} />
          <Fact label="RH 500 hPa" value={num(current.rh_500_pct, 0, "%")} />
          <Fact label="Outflow temp" value={num(current.outflow_temp_c, 1, " °C")} />
          <Fact label="850 hPa temp" value={num(current.temp_850_c, 1, " °C")} />
          <Fact label="500 hPa height" value={num(current.height_500_m, 0, " m")} />
          <Fact label="Environmental MSLP" value={num(current.environmental_pressure_mb, 0, " mb")} />
          <Fact
            label="GFS core pressure"
            value={num(current.model_central_pressure_mb, 0, " mb")}
          />
          <Fact label="Sig. wave height" value={num(current.wave_height_m, 1, " m")} />
        </div>
      </div>

      {/* NHC's own reasoning, next to ours */}
      {discussion && (
        <div className="card p-4">
          <div className="card-title mb-3">NHC Forecaster Discussion</div>
          {discussion.key_messages && (
            <div className="rounded-lg border border-sky-500/25 bg-sky-500/5 p-3 mb-3">
              <div className="stat-label mb-1.5 text-sky-300">Key messages</div>
              <div className="text-sm text-slate-300 whitespace-pre-wrap leading-relaxed">
                {discussion.key_messages}
              </div>
            </div>
          )}
          <div className="text-sm text-slate-300 whitespace-pre-wrap leading-relaxed">
            {discussion.discussion}
          </div>
          {advisory?.forecaster && (
            <div className="text-[11px] text-slate-500 mt-3 font-mono">
              Forecaster {advisory.forecaster}
              {advisory.issued && ` · issued ${fmtFull(advisory.issued)}`}
              {advisory.position_accuracy_nm != null &&
                ` · position accurate within ${advisory.position_accuracy_nm} nm`}
            </div>
          )}
        </div>
      )}

      {advisory && advisory.forecasts.length > 0 && (
        <details className="card p-4">
          <summary className="card-title cursor-pointer">
            Raw NHC Forecast/Advisory (wind radii per point)
          </summary>
          <pre className="text-[11px] text-slate-400 font-mono whitespace-pre-wrap mt-3 leading-relaxed">
            {advisory.text}
          </pre>
        </details>
      )}

      <p className="text-[11px] text-slate-600 leading-relaxed">{diagnostics.caveat}</p>
    </div>
  );
}
