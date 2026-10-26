/** Colour scales for the environmental map overlays.
 *
 * The development fields share one convention so the map can be read without
 * consulting a key every time: red means the environment is helping the storm,
 * blue means it is hurting it, and the colour fades to fully transparent at
 * the threshold where the ingredient stops mattering either way. That is why
 * shear runs red-at-zero and blue-at-strong, the opposite of its raw magnitude.
 *
 * Pressure and 500 hPa height are not favourability at all — they steer rather
 * than strengthen — so they use a separate amber-ridge / violet-trough palette
 * that cannot be mistaken for the red-good scale.
 */

export type FieldKey =
  | "favourability"
  | "sst_c"
  | "shear_kt"
  | "rh_700_pct"
  | "mslp_mb"
  | "height_500_m";

/** [value, r, g, b, alpha] — interpolated in RGBA, so alpha fades at neutral. */
type Stop = [number, number, number, number, number];

export interface FieldSpec {
  key: FieldKey;
  label: string;
  short: string;
  unit: string;
  /** Which way the palette reads, for the legend caption. */
  meaning: string;
  description: string;
  stops: Stop[];
  /** Decimal places when printing a sampled value. */
  digits: number;
}

const FAVOURABILITY: Stop[] = [
  [0, 30, 58, 138, 0.8],
  [20, 37, 99, 235, 0.6],
  [35, 125, 211, 252, 0.3],
  [50, 226, 232, 240, 0],
  [65, 251, 191, 36, 0.32],
  [80, 249, 115, 22, 0.55],
  [100, 220, 38, 38, 0.8],
];

const SST: Stop[] = [
  [18, 30, 64, 175, 0.78],
  [22, 56, 189, 248, 0.55],
  [25, 125, 211, 252, 0.28],
  [26.5, 226, 232, 240, 0],
  [28, 251, 191, 36, 0.35],
  [29.5, 249, 115, 22, 0.55],
  [31, 239, 68, 68, 0.72],
  [33, 159, 18, 57, 0.85],
];

const SHEAR: Stop[] = [
  [0, 190, 18, 60, 0.75],
  [5, 239, 68, 68, 0.6],
  [10, 249, 115, 22, 0.42],
  [15, 251, 191, 36, 0.22],
  [18, 226, 232, 240, 0],
  [25, 125, 211, 252, 0.32],
  [35, 56, 189, 248, 0.55],
  [50, 37, 99, 235, 0.75],
  [70, 30, 58, 138, 0.85],
];

const RH: Stop[] = [
  [10, 30, 58, 138, 0.78],
  [30, 56, 189, 248, 0.5],
  [45, 125, 211, 252, 0.25],
  [57, 226, 232, 240, 0],
  [70, 251, 146, 60, 0.32],
  [85, 239, 68, 68, 0.55],
  [100, 159, 18, 57, 0.72],
];

const MSLP: Stop[] = [
  [985, 139, 92, 246, 0.72],
  [1000, 167, 139, 250, 0.42],
  [1008, 196, 181, 253, 0.18],
  [1013, 226, 232, 240, 0],
  [1018, 253, 230, 138, 0.26],
  [1024, 251, 191, 36, 0.5],
  [1032, 245, 158, 11, 0.72],
];

const HEIGHT: Stop[] = [
  [5600, 139, 92, 246, 0.72],
  [5750, 167, 139, 250, 0.42],
  [5850, 196, 181, 253, 0.16],
  [5880, 226, 232, 240, 0],
  [5910, 253, 230, 138, 0.26],
  [5950, 251, 191, 36, 0.5],
  [6000, 245, 158, 11, 0.72],
];

export const FIELD_SPECS: Record<FieldKey, FieldSpec> = {
  favourability: {
    key: "favourability",
    label: "Development potential",
    short: "Potential",
    unit: "",
    meaning: "red favours intensification · blue suppresses it",
    description:
      "Composite of SST, deep-layer shear and mid-level humidity, capped by " +
      "whichever ingredient is worst rather than averaged — cool water does not " +
      "become survivable because the shear happens to be slack.",
    stops: FAVOURABILITY,
    digits: 0,
  },
  sst_c: {
    key: "sst_c",
    label: "Sea-surface temperature",
    short: "SST",
    unit: "°C",
    meaning: "transparent at 26.5 °C, the threshold a cyclone needs",
    description:
      "Ocean heat is the fuel. Below roughly 26.5 °C the surface flux cannot " +
      "sustain a warm core, so the scale is clear exactly there.",
    stops: SST,
    digits: 1,
  },
  shear_kt: {
    key: "shear_kt",
    label: "Deep-layer wind shear",
    short: "Shear",
    unit: "kt",
    meaning: "red is weak shear (helps) · blue is strong shear (tears it apart)",
    description:
      "Vector difference between the 850 and 200 hPa winds. Weak shear lets the " +
      "core stay stacked; strong shear tilts and ventilates it.",
    stops: SHEAR,
    digits: 0,
  },
  rh_700_pct: {
    key: "rh_700_pct",
    label: "Mid-level humidity",
    short: "Humidity",
    unit: "%",
    meaning: "red is moist (helps) · blue is dry air that chokes convection",
    description:
      "Relative humidity at 700 hPa. Dry air entrained into the circulation " +
      "undercuts convective bursts and drives downdrafts.",
    stops: RH,
    digits: 0,
  },
  mslp_mb: {
    key: "mslp_mb",
    label: "Surface pressure",
    short: "Pressure",
    unit: "mb",
    meaning: "amber is high pressure (ridge) · violet is low pressure",
    description:
      "Mean sea-level pressure. Ridges block and steer; the storm itself is the " +
      "deepest low on the map. This one steers rather than strengthens, so it " +
      "does not use the red-good scale.",
    stops: MSLP,
    digits: 0,
  },
  height_500_m: {
    key: "height_500_m",
    label: "500 hPa height",
    short: "500 hPa",
    unit: "m",
    meaning: "amber is the steering ridge · violet is a trough",
    description:
      "The mid-level height field is what actually steers a mature cyclone: it " +
      "flows along the height contours, keeping higher heights to its right in " +
      "the northern hemisphere.",
    stops: HEIGHT,
    digits: 0,
  },
};

export const FIELD_ORDER: FieldKey[] = [
  "favourability",
  "sst_c",
  "shear_kt",
  "rh_700_pct",
  "mslp_mb",
  "height_500_m",
];

/** Interpolate a value through a stop table, returning premultiplied-ready RGBA. */
export function sampleColor(stops: Stop[], value: number): [number, number, number, number] {
  if (value <= stops[0][0]) {
    const [, r, g, b, a] = stops[0];
    return [r, g, b, a];
  }
  const last = stops[stops.length - 1];
  if (value >= last[0]) return [last[1], last[2], last[3], last[4]];

  for (let i = 0; i < stops.length - 1; i++) {
    const [v0, r0, g0, b0, a0] = stops[i];
    const [v1, r1, g1, b1, a1] = stops[i + 1];
    if (value >= v0 && value <= v1) {
      const t = v1 === v0 ? 0 : (value - v0) / (v1 - v0);
      return [
        r0 + (r1 - r0) * t,
        g0 + (g1 - g0) * t,
        b0 + (b1 - b0) * t,
        a0 + (a1 - a0) * t,
      ];
    }
  }
  return [last[1], last[2], last[3], last[4]];
}

/** CSS gradient mirroring the scale, for the legend bar. */
export function legendGradient(spec: FieldSpec): string {
  const { stops } = spec;
  const min = stops[0][0];
  const max = stops[stops.length - 1][0];
  const parts = stops.map(([v, r, g, b, a]) => {
    const pct = ((v - min) / (max - min)) * 100;
    // Legend swatches read better opaque; keep relative weight, lift the floor.
    const alpha = Math.min(1, 0.18 + a);
    return `rgba(${Math.round(r)},${Math.round(g)},${Math.round(b)},${alpha.toFixed(2)}) ${pct.toFixed(1)}%`;
  });
  return `linear-gradient(to right, ${parts.join(", ")})`;
}

export const legendRange = (spec: FieldSpec): [number, number] => [
  spec.stops[0][0],
  spec.stops[spec.stops.length - 1][0],
];
