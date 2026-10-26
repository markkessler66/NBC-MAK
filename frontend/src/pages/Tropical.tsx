import { useEffect, useState } from "react";
import { api } from "../api";
import { usePoll } from "../hooks";
import { ageString } from "../lib/format";
import { BasinMap } from "../components/tropical/BasinMap";
import { StormCard } from "../components/tropical/StormCard";
import { StormDetail } from "../components/tropical/StormDetail";

export function Tropical() {
  const { data, error } = usePoll(api.tropical, 5 * 60 * 1000);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Drop the selection if NHC stops carrying that system while it is open.
  const stillActive = data?.storms.some((s) => s.id === selectedId) ?? true;
  useEffect(() => {
    if (!stillActive) setSelectedId(null);
  }, [stillActive]);

  if (error && !data) {
    return <div className="card p-4 text-sm text-amber-300">Tropical feed warming up: {error}</div>;
  }
  if (!data) return <div className="card p-4 text-sm text-slate-500">Loading tropical data…</div>;

  if (selectedId && stillActive) {
    return <StormDetail stormId={selectedId} onBack={() => setSelectedId(null)} />;
  }

  return (
    <div className="space-y-4">
      <div className="card p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="card-title">Active Systems — NHC</div>
          <div className="text-[11px] text-slate-500 font-mono">
            updated {ageString(data.fetched_at)}
          </div>
        </div>
        <BasinMap storms={data.storms} onSelect={setSelectedId} />
        {data.storms.length > 0 && (
          <p className="text-[11px] text-slate-500 mt-2">
            Shaded areas are NHC cones of uncertainty; numbered markers are official forecast
            positions in hours ahead. Click a storm for its full analysis.
          </p>
        )}
      </div>

      {data.storms.length === 0 ? (
        <div className="card p-4 text-sm text-slate-400">
          No active tropical cyclones. The Atlantic outlook below shows areas being monitored.
        </div>
      ) : (
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
          {data.storms.map((s) => (
            <StormCard key={s.id} storm={s} onOpen={setSelectedId} />
          ))}
        </div>
      )}

      <div className="grid md:grid-cols-2 gap-4">
        {data.outlooks.map((o) => (
          <div key={o.label} className="card p-4">
            <div className="card-title mb-3">{o.label}</div>
            <a href={o.link} target="_blank" rel="noreferrer">
              <img
                src={o.image}
                alt={o.label}
                className="rounded-lg w-full"
                loading="lazy"
                referrerPolicy="no-referrer"
              />
            </a>
          </div>
        ))}
      </div>

      <div className="text-[11px] text-slate-600">
        Tracks, cones, wind radii, and per-storm environmental diagnostics come from NHC advisories
        and GFS. Outlook graphics are served by the National Hurricane Center.
      </div>
    </div>
  );
}
