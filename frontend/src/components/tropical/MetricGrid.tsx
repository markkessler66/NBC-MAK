import type { Metric } from "../../types";
import { toneStyle } from "./stormStyle";

/** Renders backend-classified metrics: value, category, and why it matters.
 *
 *  The classification and its explanation are computed server-side so the
 *  meteorological thresholds live in one place rather than being duplicated
 *  in the UI.
 */
export function MetricGrid({ metrics, columns = 2 }: { metrics: Metric[]; columns?: 2 | 3 }) {
  const grid = columns === 3 ? "sm:grid-cols-2 xl:grid-cols-3" : "sm:grid-cols-2";
  return (
    <div className={`grid ${grid} gap-3`}>
      {metrics.map((m) => {
        const tone = toneStyle(m.tone);
        return (
          <div key={m.key} className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
            <div className="flex items-start justify-between gap-2">
              <span className="stat-label">{m.label}</span>
              {m.category && (
                <span className={`text-[10px] px-1.5 py-0.5 rounded border shrink-0 ${tone.badge}`}>
                  {m.category}
                </span>
              )}
            </div>
            <div className={`font-mono text-lg mt-1 ${tone.text}`}>{m.display}</div>
            <p className="text-[11px] text-slate-500 mt-1.5 leading-relaxed">{m.note}</p>
          </div>
        );
      })}
    </div>
  );
}
