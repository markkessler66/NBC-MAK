import { fmtFull } from "../../lib/format";
import type { FieldKey } from "./fieldScales";
import { FIELD_ORDER, FIELD_SPECS, legendGradient, legendRange } from "./fieldScales";

interface Props {
  value: FieldKey | null;
  onChange: (key: FieldKey | null) => void;
  hour: number;
  leadHours: number[];
  onHourChange: (hour: number) => void;
  validTime: string | null;
  loading?: boolean;
  note?: string;
  /** Upstream quota message; the legend is meaningless without data behind it. */
  unavailable?: string | null;
  /** Atmosphere layers are empty but the cached ocean grid still renders. */
  degraded?: string | null;
}

const TICKS = 5;

export function FieldControls({
  value,
  onChange,
  hour,
  leadHours,
  onHourChange,
  validTime,
  loading = false,
  note,
  unavailable,
  degraded,
}: Props) {
  const spec = value ? FIELD_SPECS[value] : null;
  const [min, max] = spec ? legendRange(spec) : [0, 1];

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-[11px] uppercase tracking-wide text-slate-500">Overlay</label>
        <select
          className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-sm text-slate-200"
          value={value ?? ""}
          onChange={(e) => onChange((e.target.value || null) as FieldKey | null)}
        >
          <option value="">None</option>
          {FIELD_ORDER.map((key) => (
            <option key={key} value={key}>
              {FIELD_SPECS[key].label}
            </option>
          ))}
        </select>

        {leadHours.length > 0 && (
          <>
            <label className="text-[11px] uppercase tracking-wide text-slate-500 ml-2">
              Lead
            </label>
            <select
              className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-sm text-slate-200"
              value={hour}
              onChange={(e) => onHourChange(Number(e.target.value))}
            >
              {leadHours.map((h) => (
                <option key={h} value={h}>
                  {h === 0 ? "Now" : `+${h} h`}
                </option>
              ))}
            </select>
          </>
        )}

        {loading && <span className="text-[11px] text-slate-500">sampling…</span>}
        {!loading && !unavailable && validTime && (
          <span className="text-[11px] text-slate-500">valid {fmtFull(validTime)}</span>
        )}
      </div>

      {!loading && unavailable && (
        <p className="text-[11px] text-amber-300/80 leading-relaxed">
          Map layers unavailable — {unavailable}
        </p>
      )}

      {!loading && !unavailable && degraded && value !== "sst_c" && (
        <p className="text-[11px] text-amber-300/80 leading-relaxed">
          Only sea-surface temperature is available right now — the model feed is over its
          request quota, so the atmospheric layers are blank until it resets.
        </p>
      )}

      {spec && !unavailable && (
        <div>
          <div
            className="h-2.5 rounded border border-slate-700"
            style={{ background: legendGradient(spec) }}
          />
          <div className="flex justify-between mt-1 font-mono text-[10px] text-slate-500">
            {Array.from({ length: TICKS }, (_, i) => {
              const v = min + ((max - min) * i) / (TICKS - 1);
              return <span key={i}>{spec.digits ? v.toFixed(spec.digits) : Math.round(v)}</span>;
            })}
          </div>
          <p className="text-[11px] text-slate-400 mt-1">
            <span className="text-slate-300">
              {spec.label}
              {spec.unit ? ` (${spec.unit})` : ""}
            </span>{" "}
            — {spec.meaning}
          </p>
          <p className="text-[11px] text-slate-500 leading-relaxed mt-0.5">{spec.description}</p>
          {note && <p className="text-[11px] text-slate-600 mt-0.5">{note}</p>}
        </div>
      )}
    </div>
  );
}
