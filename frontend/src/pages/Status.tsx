import { api } from "../api";
import { usePoll } from "../hooks";
import { ageString } from "../lib/format";

export function Status() {
  const { data, error } = usePoll(api.status, 15 * 1000);

  if (error && !data) return <div className="card p-4 text-sm text-amber-300">{error}</div>;
  if (!data) return <div className="card p-4 text-sm text-slate-500">Loading system status…</div>;

  return (
    <div className="space-y-4">
      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
        {data.sources.map((s) => (
          <div key={s.source} className="card p-3.5">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-slate-200">{s.label}</span>
              <span
                className={`w-2.5 h-2.5 rounded-full ${
                  s.ok ? "bg-emerald-400" : s.fetched_at ? "bg-rose-400" : "bg-slate-600"
                }`}
              />
            </div>
            <div className="text-[11px] text-slate-500 font-mono mt-1.5">
              {s.fetched_at ? (
                <>
                  fetched {ageString(s.fetched_at)} · {s.duration_ms?.toFixed(0)} ms
                  {s.items != null && ` · ${s.items} items`}
                </>
              ) : (
                "no fetch yet"
              )}
            </div>
            {s.extra?.cycle && (
              <div className="text-[11px] text-sky-400/80 font-mono mt-1">
                run {s.extra.cycle.replace(":00:00Z", "Z").replace("T", " ")} · {s.extra.files} files ·
                ingested +{s.extra.init_to_ingest_min} min after init
              </div>
            )}
            {!s.ok && s.message !== "not yet fetched" && (
              <div className="text-[11px] text-rose-300/90 font-mono mt-1 break-all">{s.message}</div>
            )}
          </div>
        ))}
      </div>

      <div className="card p-4">
        <div className="card-title mb-3">Recent Ingest Events</div>
        <div className="overflow-x-auto max-h-96 overflow-y-auto">
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-slate-500 border-b border-slate-800 sticky top-0 bg-slate-900">
                <th className="text-left py-1.5 font-medium">Source</th>
                <th className="text-left font-medium">Started</th>
                <th className="text-right font-medium">Duration</th>
                <th className="text-right font-medium">Items</th>
                <th className="text-left font-medium pl-3">Result</th>
              </tr>
            </thead>
            <tbody>
              {data.archive.recent_events.map((e, i) => (
                <tr key={i} className="border-b border-slate-800/50">
                  <td className="py-1.5 text-slate-300">{e.source}</td>
                  <td className="text-slate-500">{e.started_at.slice(0, 19)}</td>
                  <td className="text-right text-slate-400">{e.duration_ms.toFixed(0)} ms</td>
                  <td className="text-right text-slate-400">{e.items}</td>
                  <td className={`pl-3 ${e.ok ? "text-emerald-400" : "text-rose-400"}`}>
                    {e.ok ? "ok" : e.message.slice(0, 60)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
