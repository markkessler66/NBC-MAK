import { compass, num } from "../../lib/format";
import type { StormData } from "../../types";
import { intensityTag, stormColor, stormTitle } from "./stormStyle";

interface Props {
  storm: StormData;
  onOpen: (stormId: string) => void;
}

export function StormCard({ storm: s, onOpen }: Props) {
  const color = stormColor(s.classification);
  const peak = s.track?.points?.reduce<number | null>(
    (best, p) => (p.wind_kt != null && (best == null || p.wind_kt > best) ? p.wind_kt : best),
    null,
  );
  const strengthening = peak != null && s.intensity_kt != null && peak > s.intensity_kt;

  return (
    <button
      type="button"
      onClick={() => onOpen(s.id)}
      className="card p-4 text-left w-full transition hover:border-slate-600 hover:bg-slate-900
                 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className="w-3 h-3 rounded-full shrink-0"
            style={{ background: color, boxShadow: `0 0 10px -1px ${color}` }}
          />
          <span className="font-semibold text-slate-100 truncate">{stormTitle(s)}</span>
        </div>
        <span className="text-[11px] text-slate-500 shrink-0">{s.basin}</span>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 mt-3 text-sm font-mono">
        <div>
          <span className="stat-label block">Max winds</span>
          {num(s.intensity_mph, 0, " mph")} ({num(s.intensity_kt, 0, " kt")})
        </div>
        <div>
          <span className="stat-label block">Pressure</span>
          {num(s.pressure_mb, 0, " mb")}
        </div>
        <div>
          <span className="stat-label block">Position</span>
          {s.lat?.toFixed(1)}N / {Math.abs(s.lon ?? 0).toFixed(1)}W
        </div>
        <div>
          <span className="stat-label block">Movement</span>
          {s.movement_dir_deg != null
            ? `${compass(s.movement_dir_deg)} ${num(s.movement_speed_mph, 0, " mph")}`
            : "—"}
        </div>
      </div>

      <div className="flex items-center justify-between gap-2 mt-3 pt-3 border-t border-slate-800">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span
            className="text-[11px] px-1.5 py-0.5 rounded border font-medium"
            style={{ color, borderColor: `${color}55`, background: `${color}1a` }}
          >
            {intensityTag(s)}
          </span>
          {s.cone && (
            <span className="text-[11px] px-1.5 py-0.5 rounded border border-slate-700 text-slate-400">
              Cone
            </span>
          )}
          {strengthening && (
            <span className="text-[11px] px-1.5 py-0.5 rounded border border-amber-500/30 bg-amber-500/10 text-amber-300">
              → {num(peak, 0, " kt")}
            </span>
          )}
        </div>
        <span className="text-xs text-sky-400 shrink-0">Full analysis →</span>
      </div>
    </button>
  );
}
