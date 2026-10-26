export const TZ = "America/Chicago";

const timeFmt = new Intl.DateTimeFormat("en-US", {
  timeZone: TZ,
  hour: "numeric",
  minute: "2-digit",
});
const dayHourFmt = new Intl.DateTimeFormat("en-US", {
  timeZone: TZ,
  weekday: "short",
  hour: "numeric",
});
const fullFmt = new Intl.DateTimeFormat("en-US", {
  timeZone: TZ,
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});
const weekdayFmt = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short" });
const dateFmt = new Intl.DateTimeFormat("en-US", { timeZone: TZ, month: "short", day: "numeric" });

export const fmtTime = (iso: string) => timeFmt.format(new Date(iso));
export const fmtDayHour = (iso: string) => dayHourFmt.format(new Date(iso));
export const fmtFull = (iso: string) => fullFmt.format(new Date(iso));

export function fmtLocalDate(dateStr: string): { weekday: string; date: string } {
  // dateStr is a local calendar date (YYYY-MM-DD); anchor at noon to dodge DST edges.
  const d = new Date(`${dateStr}T12:00:00-06:00`);
  return { weekday: weekdayFmt.format(d), date: dateFmt.format(d) };
}

export function ageString(iso: string | null | undefined): string {
  if (!iso) return "—";
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 90) return `${Math.round(secs)}s ago`;
  if (secs < 5400) return `${Math.round(secs / 60)}m ago`;
  if (secs < 172800) return `${(secs / 3600).toFixed(1)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}

export function compass(deg: number | null | undefined): string {
  if (deg == null) return "—";
  const dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  return dirs[Math.round(deg / 22.5) % 16];
}

export function num(v: number | string | null | undefined, digits = 0, suffix = ""): string {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? `${n.toFixed(digits)}${suffix}` : "—";
}

export const deg = (v: number | string | null | undefined, digits = 0) => num(v, digits, "°");

export const MODEL_COLORS: Record<string, string> = {
  hrrr: "#fb923c",
  gfs: "#f87171",
  ecmwf_ifs: "#60a5fa",
  ecmwf_aifs: "#c084fc",
  nbm: "#2dd4bf",
  nws: "#facc15",
  pangu: "#f472b6",
  consensus: "#f8fafc",
};

export const CONFIDENCE_STYLE: Record<string, { text: string; badge: string; dot: string }> = {
  high: { text: "text-emerald-400", badge: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30", dot: "bg-emerald-400" },
  medium: { text: "text-amber-400", badge: "bg-amber-500/15 text-amber-300 border-amber-500/30", dot: "bg-amber-400" },
  low: { text: "text-rose-400", badge: "bg-rose-500/15 text-rose-300 border-rose-500/30", dot: "bg-rose-400" },
  limited: { text: "text-slate-400", badge: "bg-slate-500/15 text-slate-300 border-slate-500/30", dot: "bg-slate-400" },
  unknown: { text: "text-slate-500", badge: "bg-slate-500/10 text-slate-400 border-slate-600/30", dot: "bg-slate-500" },
};

export const confStyle = (c: string | null | undefined) =>
  CONFIDENCE_STYLE[c ?? "unknown"] ?? CONFIDENCE_STYLE.unknown;
