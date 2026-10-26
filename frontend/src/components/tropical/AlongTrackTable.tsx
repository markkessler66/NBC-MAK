import { fmtFull, num } from "../../lib/format";
import type { EnvironmentPoint, TrackPoint } from "../../types";
import { pointTag } from "./stormStyle";

function shearTone(kt: number | null | undefined): string {
  if (kt == null) return "text-slate-500";
  if (kt < 10) return "text-emerald-300";
  if (kt < 20) return "text-amber-300";
  return "text-rose-300";
}

function sstTone(c: number | null | undefined, overLand: boolean): string {
  if (overLand) return "text-slate-500";
  if (c == null) return "text-slate-500";
  if (c >= 28) return "text-emerald-300";
  if (c >= 26.5) return "text-emerald-400";
  if (c >= 25) return "text-amber-300";
  return "text-rose-300";
}

/** Every sampled parameter at every official forecast point, side by side. */
export function AlongTrackTable({
  points,
  trackPoints,
}: {
  points: EnvironmentPoint[];
  trackPoints: TrackPoint[];
}) {
  const byHour = new Map(trackPoints.map((p) => [p.fcst_hour, p]));

  return (
    <div className="overflow-x-auto -mx-1 px-1">
      <table className="w-full text-sm font-mono whitespace-nowrap">
        <thead>
          <tr className="text-slate-500 border-b border-slate-800">
            {[
              "Lead",
              "Valid",
              "Position",
              "NHC wind",
              "Stage",
              "SST",
              "Shear",
              "RH 700",
              "Steering",
              "500 hPa",
            ].map((h) => (
              <th key={h} className="text-left font-normal text-[11px] uppercase tracking-wide py-1.5 pr-4">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {points.map((p) => {
            const track = byHour.get(p.fcst_hour);
            return (
              <tr key={p.fcst_hour} className="border-b border-slate-800/60">
                <td className="py-1.5 pr-4 text-slate-200">
                  {p.fcst_hour === 0 ? "Now" : `${p.fcst_hour} h`}
                </td>
                <td className="py-1.5 pr-4 text-slate-400 text-xs">
                  {p.valid_time ? fmtFull(p.valid_time) : "—"}
                </td>
                <td className="py-1.5 pr-4 text-slate-400">
                  {p.lat.toFixed(1)}N {Math.abs(p.lon).toFixed(1)}W
                </td>
                <td className="py-1.5 pr-4 text-slate-100">{num(p.nhc_wind_kt, 0, " kt")}</td>
                <td className="py-1.5 pr-4 text-slate-400 text-xs">
                  {track ? pointTag(track) : "—"}
                </td>
                <td className={`py-1.5 pr-4 ${sstTone(p.sst_c, p.over_land)}`}>
                  {p.over_land ? "over land" : num(p.sst_c, 1, " °C")}
                </td>
                <td className={`py-1.5 pr-4 ${shearTone(p.shear?.magnitude_kt)}`}>
                  {p.shear ? `${p.shear.magnitude_kt.toFixed(0)} kt ${p.shear.toward_compass}` : "—"}
                </td>
                <td className="py-1.5 pr-4 text-slate-300">{num(p.rh_700_pct, 0, "%")}</td>
                <td className="py-1.5 pr-4 text-slate-300">
                  {p.steering
                    ? `${p.steering.speed_kt?.toFixed(0)} kt ${p.steering.toward_compass}`
                    : "—"}
                </td>
                <td className="py-1.5 pr-4 text-slate-400">{num(p.height_500_m, 0, " m")}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
