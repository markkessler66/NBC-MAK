import { useState } from "react";
import { api } from "../api";
import { usePoll } from "../hooks";
import { num } from "../lib/format";

const VARS = [
  { key: "temp_f", label: "Temperature", unit: "°F" },
  { key: "dewpoint_f", label: "Dew point", unit: "°F" },
  { key: "wind_mph", label: "Wind", unit: "mph" },
  { key: "rh", label: "Humidity", unit: "%" },
];

export function Verification() {
  const [varKey, setVarKey] = useState("temp_f");
  const [days, setDays] = useState(30);
  const { data, error } = usePoll(() => api.verification(varKey, days), 5 * 60 * 1000, [varKey, days]);
  const status = usePoll(api.status, 60 * 1000);

  const unit = VARS.find((v) => v.key === varKey)?.unit ?? "";
  const modelKeys = data
    ? Object.keys(data.models).sort((a, b) => (a === "persistence" ? 1 : b === "persistence" ? -1 : a.localeCompare(b)))
    : [];

  return (
    <div className="space-y-4">
      <div className="card p-4">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <div className="card-title">Forecast Verification — MAE by lead time ({unit})</div>
          <div className="flex items-center gap-2">
            <select
              value={varKey}
              onChange={(e) => setVarKey(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-md text-xs px-2 py-1.5 text-slate-200"
            >
              {VARS.map((v) => (
                <option key={v.key} value={v.key}>
                  {v.label}
                </option>
              ))}
            </select>
            <select
              value={days}
              onChange={(e) => setDays(+e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-md text-xs px-2 py-1.5 text-slate-200"
            >
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 90 days</option>
            </select>
          </div>
        </div>

        {error && <div className="text-sm text-amber-300 mb-2">{error}</div>}

        {data && modelKeys.length === 0 && (
          <div className="text-sm text-slate-400 leading-relaxed">
            <p className="mb-2">
              No verifiable forecast/observation pairs yet — the archive is collecting.
            </p>
            <p className="text-slate-500">
              Every model refresh stores point forecasts, and every observation is archived. Once
              forecast target times start passing (a few hours from first launch), MAE / RMSE / bias
              per model and lead time will populate here automatically.
            </p>
          </div>
        )}

        {data && modelKeys.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[11px] uppercase tracking-wide text-slate-500 border-b border-slate-800">
                  <th className="text-left py-2 font-medium">Model</th>
                  {data.bucket_order.map((b) => (
                    <th key={b} className="text-right font-medium px-2">
                      {b}
                    </th>
                  ))}
                  <th className="text-right font-medium pl-3">Overall</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {modelKeys.map((mk) => {
                  const m = data.models[mk];
                  const isBaseline = mk === "persistence";
                  return (
                    <tr
                      key={mk}
                      className={`border-b border-slate-800/60 ${isBaseline ? "text-slate-500 italic" : ""}`}
                    >
                      <td className="py-1.5 font-sans text-slate-300">{m.label}</td>
                      {data.bucket_order.map((b) => {
                        const st = m.buckets[b];
                        const best = data.best_by_bucket[b] === mk;
                        return (
                          <td
                            key={b}
                            className={`text-right px-2 ${best ? "text-emerald-300 font-semibold" : ""}`}
                            title={st ? `n=${st.n} · RMSE ${st.rmse} · bias ${st.bias > 0 ? "+" : ""}${st.bias}` : ""}
                          >
                            {st ? num(st.mae, 2) : "—"}
                            {st && st.n < 20 && <span className="text-slate-600">*</span>}
                          </td>
                        );
                      })}
                      <td className="text-right pl-3 text-slate-400">
                        {m.overall ? `${num(m.overall.mae, 2)} (n=${m.overall.n})` : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="text-[11px] text-slate-600 mt-2">
              Green = best model per lead time (min 20 samples) · * = fewer than 20 samples, provisional ·
              hover cells for RMSE / bias. {data.sample_note}
            </div>
          </div>
        )}
      </div>

      {status.data && (
        <div className="card p-4">
          <div className="card-title mb-3">Archive</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 font-mono text-sm">
            <div>
              <div className="stat-label">Forecast rows</div>
              {status.data.archive.forecast_rows.toLocaleString()}
            </div>
            <div>
              <div className="stat-label">Observations</div>
              {status.data.archive.observation_rows.toLocaleString()}
            </div>
            <div>
              <div className="stat-label">Model runs stored</div>
              {status.data.archive.distinct_runs.toLocaleString()}
            </div>
            <div>
              <div className="stat-label">Archiving since</div>
              <span className="text-xs">{status.data.archive.archiving_since ?? "—"}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
