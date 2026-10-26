/** Turn a coarse lat/lon grid into a smooth image overlay for MapLibre.
 *
 * The grid arrives regular in degrees but the map draws in Web Mercator, so
 * each output row is placed by inverting the Mercator projection rather than
 * by stretching the image linearly. Without that the shading drifts against
 * the coastline by a noticeable amount over a 30-degree tall box.
 *
 * Missing samples are the ocean model's land mask. They are not filled in:
 * their weight is dropped from the interpolation and the pixel fades out, so
 * land reads as a soft hole in the field rather than an invented value.
 */
import type { FieldSpec } from "./fieldScales";
import { sampleColor } from "./fieldScales";

export interface FieldGrid {
  lats: number[];
  lons: number[];
  bounds: { west: number; east: number; south: number; north: number };
  fields: Record<string, (number | null)[][]>;
}

const RASTER_W = 512;
const RASTER_H = 512;

const mercY = (lat: number) =>
  Math.log(Math.tan(Math.PI / 4 + (Math.max(-85, Math.min(85, lat)) * Math.PI) / 360));

const invMercY = (y: number) => (360 / Math.PI) * Math.atan(Math.exp(y)) - 90;

/** Bilinear sample that tolerates holes by renormalising over valid corners. */
function sampleGrid(
  grid: (number | null)[][],
  lats: number[],
  lons: number[],
  lat: number,
  lon: number,
): number | null {
  const ny = lats.length;
  const nx = lons.length;
  if (ny < 2 || nx < 2) return null;

  const dLat = lats[1] - lats[0];
  const dLon = lons[1] - lons[0];
  const fy = (lat - lats[0]) / dLat;
  const fx = (lon - lons[0]) / dLon;
  if (fy < -0.5 || fy > ny - 0.5 || fx < -0.5 || fx > nx - 0.5) return null;

  const y0 = Math.max(0, Math.min(ny - 2, Math.floor(fy)));
  const x0 = Math.max(0, Math.min(nx - 2, Math.floor(fx)));
  const ty = Math.max(0, Math.min(1, fy - y0));
  const tx = Math.max(0, Math.min(1, fx - x0));

  let total = 0;
  let weight = 0;
  const corners: [number, number, number][] = [
    [y0, x0, (1 - ty) * (1 - tx)],
    [y0, x0 + 1, (1 - ty) * tx],
    [y0 + 1, x0, ty * (1 - tx)],
    [y0 + 1, x0 + 1, ty * tx],
  ];
  for (const [y, x, w] of corners) {
    const value = grid[y]?.[x];
    if (value == null || w === 0) continue;
    total += value * w;
    weight += w;
  }
  // Mostly-land pixels are left undrawn rather than extrapolated from one corner.
  if (weight < 0.5) return null;
  return total / weight;
}

/**
 * Render one field to a data URL plus the corner coordinates MapLibre needs.
 * Returns null when the field has no usable values at all.
 */
/** The four image corners MapLibre wants, clockwise from top-left. */
type Corners = [[number, number], [number, number], [number, number], [number, number]];

export function renderField(
  grid: FieldGrid,
  spec: FieldSpec,
): { url: string; coordinates: Corners } | null {
  const values = grid.fields[spec.key];
  if (!values) return null;

  const { west, east, south, north } = grid.bounds;
  const canvas = document.createElement("canvas");
  canvas.width = RASTER_W;
  canvas.height = RASTER_H;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;

  const image = ctx.createImageData(RASTER_W, RASTER_H);
  const data = image.data;
  const yTop = mercY(north);
  const yBot = mercY(south);

  let drew = false;
  for (let row = 0; row < RASTER_H; row++) {
    const lat = invMercY(yTop + ((row + 0.5) / RASTER_H) * (yBot - yTop));
    for (let col = 0; col < RASTER_W; col++) {
      const lon = west + ((col + 0.5) / RASTER_W) * (east - west);
      const value = sampleGrid(values, grid.lats, grid.lons, lat, lon);
      if (value == null) continue;
      const [r, g, b, a] = sampleColor(spec.stops, value);
      const i = (row * RASTER_W + col) * 4;
      data[i] = r;
      data[i + 1] = g;
      data[i + 2] = b;
      data[i + 3] = Math.round(a * 255);
      drew = true;
    }
  }
  if (!drew) return null;

  ctx.putImageData(image, 0, 0);
  return {
    url: canvas.toDataURL("image/png"),
    coordinates: [
      [west, north],
      [east, north],
      [east, south],
      [west, south],
    ],
  };
}

/** Value of a field at a position, for hover readouts. */
export function valueAt(
  grid: FieldGrid,
  key: string,
  lat: number,
  lon: number,
): number | null {
  const values = grid.fields[key];
  if (!values) return null;
  return sampleGrid(values, grid.lats, grid.lons, lat, lon);
}
