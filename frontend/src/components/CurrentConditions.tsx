import type { ObservationData } from "../types";
import { ageString, compass, deg, fmtFull, num } from "../lib/format";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="stat-label">{label}</div>
      <div className="text-sm font-medium text-slate-200 font-mono">{value}</div>
    </div>
  );
}

export function CurrentConditions({ obs }: { obs: ObservationData | null }) {
  if (!obs) {
    return (
      <div className="card p-4">
        <div className="card-title mb-2">Current Conditions</div>
        <div className="text-slate-500 text-sm">Waiting for first observation…</div>
      </div>
    );
  }

  const ageMin = (Date.now() - new Date(obs.obs_time).getTime()) / 60000;
  const stale = ageMin > 90;

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="card-title">Current Conditions</div>
        <div className={`text-[11px] font-mono ${stale ? "text-amber-400" : "text-slate-500"}`}>
          {obs.station} · {ageString(obs.obs_time)}
          {stale && " · STALE"}
        </div>
      </div>

      <div className="flex items-start gap-5">
        <div>
          <div className="text-5xl font-light text-slate-50 font-mono leading-none">
            {deg(obs.temp_f)}
          </div>
          <div className="text-sm text-slate-400 mt-1.5">{obs.description || "—"}</div>
          <div className="text-xs text-slate-500 mt-0.5">
            Feels like <span className="text-slate-300">{deg(obs.feels_like_f)}</span>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-x-5 gap-y-2.5 flex-1 min-w-0">
          <Stat label="Dew point" value={deg(obs.dewpoint_f)} />
          <Stat label="Humidity" value={num(obs.rh, 0, "%")} />
          <Stat label="Pressure" value={num(obs.pressure_mb, 1, " mb")} />
          <Stat
            label="Wind"
            value={
              obs.wind_mph != null && obs.wind_mph > 0
                ? `${compass(obs.wind_dir_deg)} ${num(obs.wind_mph, 0, " mph")}`
                : "Calm"
            }
          />
          <Stat label="Gusts" value={num(obs.gust_mph, 0, " mph")} />
          <Stat label="Visibility" value={num(obs.visibility_mi, 0, " mi")} />
          <Stat label="Precip (1h)" value={obs.precip_last_hour_in ? num(obs.precip_last_hour_in, 2, " in") : "None"} />
          <Stat label="Sky" value={obs.cloud_layer ?? "—"} />
        </div>
      </div>

      <div className="text-[11px] text-slate-600 mt-3 font-mono">
        Observed {fmtFull(obs.obs_time)} CT — fetched {ageString(obs.fetched_at)}
      </div>
    </div>
  );
}
