import type { DailySummary } from "../types";
import { confStyle, fmtLocalDate, num } from "../lib/format";

export function DailyStrip({ daily }: { daily: DailySummary[] }) {
  return (
    <div className="card p-4">
      <div className="card-title mb-3">10-Day Consensus Outlook</div>
      <div className="grid grid-flow-col auto-cols-fr gap-2 overflow-x-auto">
        {daily.map((d, i) => {
          const { weekday, date } = fmtLocalDate(d.date);
          const cs = confStyle(d.confidence);
          return (
            <div
              key={d.date}
              className="bg-slate-800/50 border border-slate-800 rounded-lg px-2 py-2.5 text-center min-w-[86px]"
            >
              <div className="text-xs font-semibold text-slate-300">{i === 0 ? "Today" : weekday}</div>
              <div className="text-[10px] text-slate-500 mb-1.5">{date}</div>
              <div className="font-mono text-sm">
                <span className="text-slate-50 font-semibold">{Math.round(d.hi)}°</span>
                <span className="text-slate-500 ml-1.5">{Math.round(d.lo)}°</span>
              </div>
              <div className="text-[10px] text-slate-400 mt-1 truncate" title={d.conditions}>
                {d.conditions}
              </div>
              <div className="text-[10px] text-sky-400/80 font-mono mt-0.5">
                {d.pop != null && d.pop >= 5 ? `${Math.round(d.pop)}%` : "\u00a0"}
              </div>
              <div
                className="flex items-center justify-center gap-1 mt-1.5"
                title={`Temp spread up to ${num(d.temp_spread_max, 1, "°F")} — confidence ${d.confidence}`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${cs.dot}`} />
                <span className="text-[9px] text-slate-500 font-mono">±{num(d.temp_spread_max, 0)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
