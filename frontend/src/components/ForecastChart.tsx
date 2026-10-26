import { useMemo, useState } from "react";
import type { ForecastPayload } from "../types";
import { MODEL_COLORS, ageString } from "../lib/format";
import { useECharts } from "./useECharts";

const VARIABLES: { key: string; label: string; unit: string; ensemble?: boolean }[] = [
  { key: "temp_f", label: "Temperature", unit: "°F", ensemble: true },
  { key: "dewpoint_f", label: "Dew point", unit: "°F" },
  { key: "precip_prob", label: "Precip probability", unit: "%" },
  { key: "precip_in", label: "Precip amount", unit: "in", ensemble: true },
  { key: "wind_mph", label: "Wind", unit: "mph", ensemble: true },
  { key: "gust_mph", label: "Gusts", unit: "mph" },
  { key: "cloud_pct", label: "Cloud cover", unit: "%" },
  { key: "cape", label: "CAPE", unit: "J/kg" },
];

const RANGES = [
  { label: "24h", hours: 24 },
  { label: "48h", hours: 48 },
  { label: "7d", hours: 168 },
  { label: "10d", hours: 240 },
];

export function ForecastChart({ payload }: { payload: ForecastPayload }) {
  const [varKey, setVarKey] = useState("temp_f");
  const [range, setRange] = useState(168);

  const option = useMemo(() => {
    const variable = VARIABLES.find((v) => v.key === varKey)!;
    const n = Math.min(range + 1, payload.timeline.length);
    const times = payload.timeline.slice(0, n).map((t) => new Date(t).getTime());
    const pair = (col: (number | null)[] | undefined) =>
      times.map((t, i) => [t, col?.[i] ?? null]);

    const series: object[] = [];

    // GEFS ensemble p10–p90 band (drawn first, underneath everything).
    const ens = payload.ensemble?.percentiles?.[varKey];
    if (ens && variable.ensemble) {
      series.push(
        {
          name: "GEFS p10", type: "line", data: pair(ens.p10), lineStyle: { opacity: 0 },
          symbol: "none", stack: "ens", silent: true, tooltip: { show: false },
        },
        {
          name: `GEFS p10–p90 (${payload.ensemble!.members} members)`, type: "line",
          data: times.map((t, i) => {
            const lo = ens.p10[i], hi = ens.p90[i];
            return [t, lo != null && hi != null ? +(hi - lo).toFixed(2) : null];
          }),
          lineStyle: { opacity: 0 }, symbol: "none", stack: "ens",
          areaStyle: { color: "rgba(56,189,248,0.14)" }, silent: true, tooltip: { show: false },
        },
      );
    }

    // Model disagreement band (consensus min → max).
    const cons = payload.consensus[varKey];
    if (cons) {
      series.push(
        {
          name: "range-lo", type: "line", data: pair(cons.min), lineStyle: { opacity: 0 },
          symbol: "none", stack: "spread", silent: true, tooltip: { show: false },
        },
        {
          name: "Model range", type: "line",
          data: times.map((t, i) => {
            const lo = cons.min[i], hi = cons.max[i];
            return [t, lo != null && hi != null ? +(hi - lo).toFixed(2) : null];
          }),
          lineStyle: { opacity: 0 }, symbol: "none", stack: "spread",
          areaStyle: { color: "rgba(148,163,184,0.18)" }, silent: true, tooltip: { show: false },
        },
      );
    }

    for (const m of Object.values(payload.models)) {
      const col = m.values[varKey];
      if (!col) continue;
      // Daily-resolution models (e.g. Pangu's 24 h steps) render as dotted
      // markers with a dashed connector instead of an invisible gappy line.
      const points = col.filter((v) => v != null).length;
      const sparse = points > 0 && points < n / 6;
      series.push({
        name: m.label, type: "line", data: pair(col),
        symbol: sparse ? "circle" : "none", symbolSize: 6,
        connectNulls: sparse,
        lineStyle: {
          width: sparse ? 1 : 1.2,
          type: sparse ? "dashed" : "solid",
          color: MODEL_COLORS[m.key] ?? "#94a3b8",
        },
        itemStyle: { color: MODEL_COLORS[m.key] ?? "#94a3b8" },
      });
    }

    if (cons) {
      series.push({
        name: "Consensus", type: "line", data: pair(cons.median),
        symbol: "none", lineStyle: { width: 2.6, color: MODEL_COLORS.consensus },
        itemStyle: { color: MODEL_COLORS.consensus }, z: 10,
      });
    }

    return {
      backgroundColor: "transparent",
      animation: false,
      grid: { left: 48, right: 16, top: 36, bottom: 28 },
      legend: {
        top: 0,
        textStyle: { color: "#94a3b8", fontSize: 11 },
        data: [...Object.values(payload.models).map((m) => m.label), "Consensus"],
        inactiveColor: "#334155",
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#0f172acc",
        borderColor: "#334155",
        textStyle: { color: "#e2e8f0", fontSize: 12 },
        valueFormatter: (v: unknown) => (v == null ? "—" : `${(+(v as number)).toFixed(1)} ${variable.unit}`),
      },
      xAxis: {
        type: "time",
        axisLine: { lineStyle: { color: "#334155" } },
        axisLabel: { color: "#64748b", fontSize: 11, hideOverlap: true },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        scale: true,
        name: variable.unit,
        nameTextStyle: { color: "#64748b" },
        axisLabel: { color: "#64748b", fontSize: 11 },
        splitLine: { lineStyle: { color: "#1e293b" } },
      },
      series,
    };
  }, [payload, varKey, range]);

  const chartRef = useECharts(option);

  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        <div className="card-title">Multi-Model Forecast — {payload.location.name}</div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={varKey}
            onChange={(e) => setVarKey(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded-md text-xs px-2 py-1.5 text-slate-200"
          >
            {VARIABLES.map((v) => (
              <option key={v.key} value={v.key}>
                {v.label}
              </option>
            ))}
          </select>
          <div className="flex rounded-md overflow-hidden border border-slate-700">
            {RANGES.map((r) => (
              <button
                key={r.hours}
                onClick={() => setRange(r.hours)}
                className={`px-2.5 py-1.5 text-xs font-medium ${
                  range === r.hours ? "bg-sky-600 text-white" : "bg-slate-800 text-slate-400 hover:text-slate-200"
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div ref={chartRef} className="h-80 w-full" />
      <div className="text-[11px] text-slate-600 font-mono">
        Gray band = model disagreement · blue band = GEFS ensemble spread · generated {ageString(payload.generated_at)}
      </div>
    </div>
  );
}
