import { useMemo, useState } from "react";
import type { ForecastPayload } from "../types";
import { MODEL_COLORS, TZ, confStyle, deg, fmtFull, num } from "../lib/format";

/** Index of the first timeline hour matching `hour` local time, at least `minIdx` in. */
function findLocalHour(timeline: string[], hour: number, minIdx: number): number {
  const fmt = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", hour12: false });
  for (let i = minIdx; i < timeline.length; i++) {
    if (parseInt(fmt.format(new Date(timeline[i])), 10) === hour) return i;
  }
  return Math.min(minIdx, timeline.length - 1);
}

export function ComparisonPanel({ payload }: { payload: ForecastPayload }) {
  const quickPicks = useMemo(
    () => [
      { label: "+6h", idx: Math.min(6, payload.timeline.length - 1) },
      { label: "Tomorrow 4 PM", idx: findLocalHour(payload.timeline, 16, 18) },
      { label: "+48h", idx: Math.min(48, payload.timeline.length - 1) },
      { label: "+72h", idx: Math.min(72, payload.timeline.length - 1) },
    ],
    [payload],
  );

  const [idx, setIdx] = useState(() => quickPicks[1].idx);
  const i = Math.min(idx, payload.timeline.length - 1);

  const cons = payload.consensus;
  const confidence = payload.confidence_temp[i] ?? "unknown";
  const cs = confStyle(confidence);

  const rows = Object.values(payload.models).map((m) => ({
    key: m.key,
    label: m.label,
    isAi: m.is_ai,
    runInfo: m.init_time
      ? `Run ${m.init_time.replace(":00:00Z", "Z").replace("T", " ")} (native NOAA)`
      : `Fetched ${m.fetched_at.slice(11, 16)}Z (API feed)`,
    temp: m.values.temp_f?.[i] ?? null,
    dew: m.values.dewpoint_f?.[i] ?? null,
    pop: m.values.precip_prob?.[i] ?? null,
    wind: m.values.wind_mph?.[i] ?? null,
    cloud: m.values.cloud_pct?.[i] ?? null,
  }));

  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="card-title">Model Comparison</div>
        <div className="flex gap-1.5">
          {quickPicks.map((q) => (
            <button
              key={q.label}
              onClick={() => setIdx(q.idx)}
              className={`px-2 py-1 text-[11px] rounded border ${
                i === q.idx
                  ? "bg-sky-600 border-sky-500 text-white"
                  : "bg-slate-800 border-slate-700 text-slate-400 hover:text-slate-200"
              }`}
            >
              {q.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mb-3">
        <input
          type="range"
          min={0}
          max={payload.timeline.length - 1}
          value={i}
          onChange={(e) => setIdx(+e.target.value)}
          className="w-full accent-sky-500"
        />
        <div className="text-sm text-slate-200 font-medium">
          {fmtFull(payload.timeline[i])} CT
          <span className="text-slate-500 text-xs ml-2 font-mono">+{i}h</span>
        </div>
      </div>

      <table className="w-full text-sm">
        <thead>
          <tr className="text-[11px] uppercase tracking-wide text-slate-500 border-b border-slate-800">
            <th className="text-left py-1.5 font-medium">Model</th>
            <th className="text-right font-medium">Temp</th>
            <th className="text-right font-medium">Dew pt</th>
            <th className="text-right font-medium">PoP</th>
            <th className="text-right font-medium">Wind</th>
            <th className="text-right font-medium">Cloud</th>
          </tr>
        </thead>
        <tbody className="font-mono">
          {rows.map((r) => (
            <tr key={r.key} className="border-b border-slate-800/60">
              <td className="py-1.5 font-sans" title={r.runInfo}>
                <span className="inline-block w-2 h-2 rounded-full mr-2" style={{ background: MODEL_COLORS[r.key] }} />
                <span className="text-slate-300">{r.label}</span>
                {r.isAi && (
                  <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/30">
                    AI
                  </span>
                )}
              </td>
              <td className="text-right text-slate-200">{deg(r.temp, 1)}</td>
              <td className="text-right text-slate-400">{deg(r.dew, 0)}</td>
              <td className="text-right text-slate-400">{num(r.pop, 0, "%")}</td>
              <td className="text-right text-slate-400">{num(r.wind, 0)}</td>
              <td className="text-right text-slate-400">{num(r.cloud, 0, "%")}</td>
            </tr>
          ))}
          <tr className="bg-slate-800/40">
            <td className="py-2 font-sans font-semibold text-slate-50">SYSTEM CONSENSUS</td>
            <td className="text-right font-semibold text-slate-50">{deg(cons.temp_f?.median[i], 1)}</td>
            <td className="text-right text-slate-300">{deg(cons.dewpoint_f?.median[i], 0)}</td>
            <td className="text-right text-slate-300">{num(cons.precip_prob?.median[i], 0, "%")}</td>
            <td className="text-right text-slate-300">{num(cons.wind_mph?.median[i], 0)}</td>
            <td className="text-right text-slate-300">{num(cons.cloud_pct?.median[i], 0, "%")}</td>
          </tr>
        </tbody>
      </table>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-3 text-xs">
        <span className={`px-2 py-0.5 rounded-full border text-[11px] font-semibold ${cs.badge}`}>
          Confidence: {confidence}
        </span>
        <span className="text-slate-400 font-mono">
          Temp range {deg(cons.temp_f?.min[i], 1)}–{deg(cons.temp_f?.max[i], 1)} · spread{" "}
          {num(cons.temp_f?.spread[i], 1, "°F")} · {cons.temp_f?.count[i] ?? 0} models
        </span>
      </div>
    </div>
  );
}
