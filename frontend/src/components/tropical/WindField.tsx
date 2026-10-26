import type { Quadrants } from "../../types";

const THRESHOLDS = [
  { kt: "34", label: "34 kt (tropical storm)", color: "#38bdf8" },
  { kt: "50", label: "50 kt (strong gale)", color: "#f59e0b" },
  { kt: "64", label: "64 kt (hurricane)", color: "#f43f5e" },
];

const QUADRANTS: { key: keyof Quadrants; label: string; start: number }[] = [
  { key: "ne", label: "NE", start: 0 },
  { key: "se", label: "SE", start: 90 },
  { key: "sw", label: "SW", start: 180 },
  { key: "nw", label: "NW", start: 270 },
];

const SIZE = 150;
const CENTRE = SIZE / 2;
const MAX_PX = CENTRE - 12;

function wedge(radiusPx: number, startDeg: number): string {
  if (radiusPx <= 0) return "";
  const point = (deg: number) => {
    const rad = (deg * Math.PI) / 180;
    return `${(CENTRE + radiusPx * Math.sin(rad)).toFixed(2)},${(
      CENTRE -
      radiusPx * Math.cos(rad)
    ).toFixed(2)}`;
  };
  return `M ${CENTRE},${CENTRE} L ${point(startDeg)} A ${radiusPx},${radiusPx} 0 0 1 ${point(
    startDeg + 90,
  )} Z`;
}

/** Quadrant wind radii, drawn to scale so the field's asymmetry is visible. */
export function WindField({
  radii,
  sizeClass,
  note,
  seas,
}: {
  radii: Record<string, { quadrants_nm: Quadrants; max_nm: number; mean_nm: number; mean_km: number }>;
  sizeClass: string | null;
  note: string;
  seas?: ({ threshold: number; unit: string } & Quadrants) | null;
}) {
  const present = THRESHOLDS.filter((t) => radii[t.kt]);
  if (!present.length) return null;
  const largest = Math.max(...present.map((t) => radii[t.kt].max_nm), 1);
  const scale = MAX_PX / largest;

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="card-title">Wind Field — Quadrant Radii</div>
        {sizeClass && (
          <span className="text-[11px] px-1.5 py-0.5 rounded border border-slate-700 text-slate-300">
            {sizeClass} storm
          </span>
        )}
      </div>

      <div className="flex flex-wrap gap-5 items-start">
        <svg width={SIZE} height={SIZE} className="shrink-0" role="img" aria-label="Wind radii by quadrant">
          <circle cx={CENTRE} cy={CENTRE} r={MAX_PX} fill="none" stroke="#1e293b" strokeWidth="1" />
          <line x1={CENTRE} y1={6} x2={CENTRE} y2={SIZE - 6} stroke="#1e293b" strokeWidth="1" />
          <line x1={6} y1={CENTRE} x2={SIZE - 6} y2={CENTRE} stroke="#1e293b" strokeWidth="1" />
          {/* Widest threshold first so the tighter cores draw on top. */}
          {[...present].reverse().map((t) =>
            QUADRANTS.map((q) => {
              const path = wedge(radii[t.kt].quadrants_nm[q.key] * scale, q.start);
              return path ? (
                <path
                  key={`${t.kt}-${q.key}`}
                  d={path}
                  fill={t.color}
                  fillOpacity={0.3}
                  stroke={t.color}
                  strokeOpacity={0.75}
                  strokeWidth="1"
                />
              ) : null;
            }),
          )}
          <circle cx={CENTRE} cy={CENTRE} r={3} fill="#f8fafc" />
          <text x={CENTRE + 4} y={12} fill="#64748b" fontSize="9">
            N
          </text>
        </svg>

        <div className="flex-1 min-w-[240px]">
          <table className="w-full text-sm font-mono">
            <thead>
              <tr className="text-slate-500">
                <th className="text-left font-normal text-[11px] uppercase tracking-wide pb-1">Wind</th>
                {QUADRANTS.map((q) => (
                  <th key={q.key} className="text-right font-normal text-[11px] uppercase pb-1">
                    {q.label}
                  </th>
                ))}
                <th className="text-right font-normal text-[11px] uppercase pb-1">Mean</th>
              </tr>
            </thead>
            <tbody>
              {present.map((t) => (
                <tr key={t.kt} className="border-t border-slate-800">
                  <td className="py-1.5" style={{ color: t.color }}>
                    {t.kt} kt
                  </td>
                  {QUADRANTS.map((q) => (
                    <td key={q.key} className="text-right text-slate-300">
                      {radii[t.kt].quadrants_nm[q.key]}
                    </td>
                  ))}
                  <td className="text-right text-slate-400">{radii[t.kt].mean_km} km</td>
                </tr>
              ))}
            </tbody>
          </table>
          {seas && (
            <p className="text-[11px] text-slate-400 mt-2 font-mono">
              <span className="text-slate-500">{seas.threshold} {seas.unit} seas</span>{" "}
              {QUADRANTS.map((q) => `${q.label} ${seas[q.key]}`).join("  ")}
            </p>
          )}
          <p className="text-[11px] text-slate-500 mt-2 leading-relaxed">
            Values in nautical miles. {note}
          </p>
        </div>
      </div>
    </div>
  );
}
