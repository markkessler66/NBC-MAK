import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api";
import type { ScenarioAdjustments, ScenarioPayload } from "../../types";
import { useECharts } from "../useECharts";

const NEUTRAL: ScenarioAdjustments = {
  shear_delta_kt: 0,
  sst_delta_c: 0,
  rh_delta_pct: 0,
  ridge_factor: 1,
};

interface Control {
  key: keyof ScenarioAdjustments;
  label: string;
  min: number;
  max: number;
  step: number;
  /** Rendered next to the slider, e.g. "-8 kt". */
  format: (v: number) => string;
  hint: string;
}

const CONTROLS: Control[] = [
  {
    key: "shear_delta_kt",
    label: "Deep-layer shear",
    min: -30,
    max: 30,
    step: 1,
    format: (v) => (v === 0 ? "as forecast" : `${v > 0 ? "+" : ""}${v} kt`),
    hint: "Less shear lets the core stay stacked and vent aloft.",
  },
  {
    key: "sst_delta_c",
    label: "Sea-surface temperature",
    min: -3,
    max: 3,
    step: 0.1,
    format: (v) => (v === 0 ? "as analysed" : `${v > 0 ? "+" : ""}${v.toFixed(1)} °C`),
    hint: "Ocean heat sets the ceiling, and the ceiling rises steeply.",
  },
  {
    key: "rh_delta_pct",
    label: "Mid-level humidity",
    min: -30,
    max: 30,
    step: 1,
    format: (v) => (v === 0 ? "as forecast" : `${v > 0 ? "+" : ""}${v}%`),
    hint: "Dry air entrained into the circulation kills convective bursts.",
  },
  {
    key: "ridge_factor",
    label: "Steering ridge strength",
    min: 0.4,
    max: 1.6,
    step: 0.05,
    format: (v) => (v === 1 ? "as analysed" : `${Math.round(v * 100)}% of analysed`),
    hint: "A weaker ridge slackens the steering flow and lets the storm turn poleward.",
  },
];

function ScenarioChart({ payload }: { payload: ScenarioPayload }) {
  const option = useMemo(() => {
    const points = payload.points ?? [];
    return {
      backgroundColor: "transparent",
      animation: false,
      grid: { left: 46, right: 20, top: 30, bottom: 40 },
      legend: {
        top: 0,
        textStyle: { color: "#94a3b8", fontSize: 11 },
        inactiveColor: "#334155",
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#0f172acc",
        borderColor: "#334155",
        textStyle: { color: "#e2e8f0", fontSize: 12 },
        valueFormatter: (v: unknown) => (v == null ? "—" : `${Math.round(v as number)} kt`),
      },
      xAxis: {
        type: "category",
        data: points.map((p) => (p.fcst_hour === 0 ? "Now" : `${p.fcst_hour}h`)),
        axisLine: { lineStyle: { color: "#334155" } },
        axisLabel: { color: "#64748b", fontSize: 11 },
      },
      yAxis: {
        type: "value",
        name: "kt",
        min: 0,
        nameTextStyle: { color: "#64748b", fontSize: 10 },
        axisLabel: { color: "#64748b", fontSize: 11 },
        splitLine: { lineStyle: { color: "#1e293b" } },
      },
      series: [
        {
          name: "NHC official",
          type: "line",
          data: points.map((p) => p.nhc_wind_kt),
          lineStyle: { width: 2.6, color: "#f8fafc" },
          itemStyle: { color: "#f8fafc" },
          symbolSize: 6,
          z: 5,
        },
        {
          name: "Your scenario",
          type: "line",
          data: points.map((p) => p.scenario_wind_kt),
          lineStyle: { width: 2.6, color: "#a78bfa" },
          itemStyle: { color: "#a78bfa" },
          areaStyle: { color: "#a78bfa", opacity: 0.12 },
          symbolSize: 6,
          z: 6,
        },
        {
          name: "Toy model, unadjusted",
          type: "line",
          data: points.map((p) => p.baseline_wind_kt),
          lineStyle: { width: 1.2, color: "#64748b", type: "dashed" },
          itemStyle: { color: "#64748b" },
          symbolSize: 0,
          z: 2,
        },
      ],
    };
  }, [payload]);

  const chartRef = useECharts(option);
  return <div ref={chartRef} className="h-64 w-full" />;
}

export function WhatIf({
  stormId,
  onScenarioChange,
}: {
  stormId: string;
  /** Lets the map draw the displaced track alongside the official one. */
  onScenarioChange?: (payload: ScenarioPayload | null) => void;
}) {
  const [adjustments, setAdjustments] = useState<ScenarioAdjustments>(NEUTRAL);
  const [payload, setPayload] = useState<ScenarioPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const notify = useRef(onScenarioChange);
  notify.current = onScenarioChange;

  // Sliders are continuous but the run is a round trip, so coalesce drags.
  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    const timer = setTimeout(() => {
      api
        .tropicalScenario(stormId, adjustments)
        .then((result) => {
          if (cancelled) return;
          setPayload(result);
          setError(null);
          notify.current?.(result);
        })
        .catch((err: Error) => !cancelled && setError(err.message))
        .finally(() => !cancelled && setBusy(false));
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [stormId, adjustments]);

  useEffect(() => () => notify.current?.(null), []);

  const dirty = useMemo(
    () => CONTROLS.some((c) => adjustments[c.key] !== NEUTRAL[c.key]),
    [adjustments],
  );

  const finalShift = payload?.points?.[payload.points.length - 1];

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-1">
        <div className="card-title">Potential Forecast — What-If Sandbox</div>
        <div className="flex items-center gap-3">
          {busy && <span className="text-[11px] text-slate-500">running…</span>}
          {dirty && (
            <button
              type="button"
              onClick={() => setAdjustments(NEUTRAL)}
              className="text-xs text-sky-400 hover:text-sky-300 rounded px-1 -mx-1
                         focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
            >
              Reset to observed
            </button>
          )}
        </div>
      </div>
      <p className="text-[11px] text-slate-500 mb-4 leading-relaxed max-w-4xl">
        Dial an ingredient away from what the models actually show and see what it would be
        worth. The model runs twice — once on the sampled environment, once on yours — and
        only the difference is applied to NHC's forecast, so with every slider centred the
        scenario reproduces the official forecast exactly.
      </p>

      <div className="grid sm:grid-cols-2 gap-x-8 gap-y-4">
        {CONTROLS.map((control) => {
          const value = adjustments[control.key];
          const changed = value !== NEUTRAL[control.key];
          return (
            <div key={control.key}>
              <div className="flex items-baseline justify-between gap-2">
                <label
                  htmlFor={`whatif-${control.key}`}
                  className="text-xs text-slate-300"
                >
                  {control.label}
                </label>
                <span
                  className={`font-mono text-xs ${
                    changed ? "text-violet-300" : "text-slate-500"
                  }`}
                >
                  {control.format(value)}
                </span>
              </div>
              <input
                id={`whatif-${control.key}`}
                type="range"
                min={control.min}
                max={control.max}
                step={control.step}
                value={value}
                onChange={(e) =>
                  setAdjustments((prev) => ({
                    ...prev,
                    [control.key]: Number(e.target.value),
                  }))
                }
                className="w-full mt-1.5 accent-violet-400"
              />
              <p className="text-[10px] text-slate-600 mt-0.5">{control.hint}</p>
            </div>
          );
        })}
      </div>

      {error && <div className="mt-4 text-sm text-amber-300">Scenario failed: {error}</div>}

      {payload && !payload.available && (
        <div className="mt-4 text-sm text-slate-500">{payload.reason}</div>
      )}

      {payload?.available && (
        <>
          <p
            className={`mt-4 text-sm leading-relaxed ${
              payload.changed ? "text-violet-200" : "text-slate-400"
            }`}
          >
            {payload.summary}
          </p>

          <div className="mt-3">
            <ScenarioChart payload={payload} />
          </div>

          {finalShift?.shift_km != null && finalShift.shift_km > 0 && (
            <p className="text-xs text-slate-400 mt-1">
              At {finalShift.fcst_hour} h the scenario centre is{" "}
              <span className="font-mono text-violet-300">
                {finalShift.shift_km} km {finalShift.shift_compass}
              </span>{" "}
              of NHC's forecast position.
            </p>
          )}

          <details className="mt-4">
            <summary className="text-[11px] text-slate-500 cursor-pointer hover:text-slate-400">
              How this is computed, and what it cannot tell you
            </summary>
            <p className="text-[11px] text-slate-500 mt-2 leading-relaxed">{payload.method}</p>
            <p className="text-[11px] text-amber-500/80 mt-2 leading-relaxed">
              {payload.caveat}
            </p>
          </details>
        </>
      )}
    </div>
  );
}
