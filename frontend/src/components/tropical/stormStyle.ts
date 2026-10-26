import type { Metric, StormData, TrackPoint } from "../../types";

/** Colour by NHC classification code, escalating with severity. */
export const CLASS_COLOR: Record<string, string> = {
  MH: "#e11d48",
  HU: "#f43f5e",
  TS: "#f59e0b",
  STS: "#f59e0b",
  TD: "#38bdf8",
  STD: "#38bdf8",
  PTC: "#a78bfa",
  PC: "#94a3b8",
  EX: "#94a3b8",
  LO: "#94a3b8",
  DB: "#94a3b8",
  WV: "#94a3b8",
};

export const stormColor = (classification: string | null | undefined) =>
  CLASS_COLOR[classification ?? ""] ?? "#94a3b8";

export const stormTitle = (s: StormData) => `${s.classification_label} ${s.name}`;

/** Short intensity tag: hurricanes get their Saffir-Simpson category. */
export function intensityTag(s: StormData): string {
  if (s.category) return `Cat ${s.category}`;
  return s.classification_label;
}

export function pointTag(p: TrackPoint): string {
  if (p.post_tropical) return "Post-tropical";
  if (p.category) return `Cat ${p.category}`;
  if (p.wind_kt == null) return "—";
  return p.wind_kt >= 34 ? "Trop. storm" : "Trop. depression";
}

/** Tone palette shared with the confidence badges on the dashboard. */
export const TONE_STYLE: Record<Metric["tone"], { text: string; badge: string; dot: string }> = {
  good: {
    text: "text-emerald-300",
    badge: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
    dot: "bg-emerald-400",
  },
  warn: {
    text: "text-amber-300",
    badge: "bg-amber-500/15 text-amber-300 border-amber-500/30",
    dot: "bg-amber-400",
  },
  bad: {
    text: "text-rose-300",
    badge: "bg-rose-500/15 text-rose-300 border-rose-500/30",
    dot: "bg-rose-400",
  },
  neutral: {
    text: "text-slate-300",
    badge: "bg-slate-500/15 text-slate-300 border-slate-600/40",
    dot: "bg-slate-400",
  },
};

export const toneStyle = (tone: Metric["tone"] | null | undefined) =>
  TONE_STYLE[tone ?? "neutral"] ?? TONE_STYLE.neutral;

/** Marker radius in pixels, scaled by intensity so strong storms read first. */
export function markerSize(windKt: number | null | undefined): number {
  if (windKt == null) return 13;
  if (windKt >= 113) return 22;
  if (windKt >= 96) return 20;
  if (windKt >= 64) return 18;
  if (windKt >= 34) return 15;
  return 13;
}
