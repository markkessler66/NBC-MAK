import type { AlertData } from "../types";
import { fmtFull } from "../lib/format";

const SEVERITY_STYLE: Record<string, string> = {
  Extreme: "border-l-rose-500 bg-rose-500/10",
  Severe: "border-l-orange-500 bg-orange-500/10",
  Moderate: "border-l-amber-500 bg-amber-500/10",
  Minor: "border-l-slate-500 bg-slate-500/10",
};

export function AlertsPanel({ alerts }: { alerts: AlertData[] }) {
  return (
    <div className="card p-4">
      <div className="card-title mb-3">
        Active Alerts{" "}
        <span className={alerts.length ? "text-rose-400" : "text-slate-600"}>({alerts.length})</span>
      </div>
      {alerts.length === 0 ? (
        <div className="text-sm text-slate-500">No active alerts for this location.</div>
      ) : (
        <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
          {alerts.map((a) => (
            <details
              key={a.id}
              className={`border-l-2 rounded-r-lg px-3 py-2 ${SEVERITY_STYLE[a.severity] ?? SEVERITY_STYLE.Minor}`}
            >
              <summary className="cursor-pointer">
                <span className="text-sm font-semibold text-slate-100">{a.event}</span>
                <span className="text-xs text-slate-400 ml-2">{a.severity}</span>
                <div className="text-xs text-slate-400 mt-0.5">
                  {a.ends ? `Until ${fmtFull(a.ends)} CT` : ""}
                </div>
              </summary>
              <div className="text-xs text-slate-300 mt-2 whitespace-pre-wrap">{a.description}</div>
              {a.instruction && (
                <div className="text-xs text-amber-200/90 mt-2 whitespace-pre-wrap">{a.instruction}</div>
              )}
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
