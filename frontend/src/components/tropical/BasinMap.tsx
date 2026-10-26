import { useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { Feature, FeatureCollection, LineString, Polygon } from "geojson";
import { BASEMAP_BASE_LAYER, BASEMAP_LABEL_LAYER, BASEMAP_SOURCES } from "../../lib/basemap";
import { compass, fmtFull, num } from "../../lib/format";
import type { StormData, TrackPoint } from "../../types";
import type { FieldGrid } from "./fieldRaster";
import { renderField } from "./fieldRaster";
import type { FieldKey } from "./fieldScales";
import { FIELD_SPECS } from "./fieldScales";
import { markerSize, pointTag, stormColor, stormTitle } from "./stormStyle";

const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

// MapLibre image sources need a URL up front, before any field is chosen. A
// fresh canvas is transparent, so this is a valid 1x1 nothing; the real overlay
// is swapped in with updateImage later.
function blankPng(): string {
  const canvas = document.createElement("canvas");
  canvas.width = 1;
  canvas.height = 1;
  return canvas.toDataURL("image/png");
}

interface Props {
  storms: StormData[];
  /** Show only this storm and frame the map on its cone. */
  focusId?: string | null;
  onSelect?: (stormId: string) => void;
  height?: string;
  /** Gridded environment to shade underneath the storms; may arrive without data. */
  fieldGrid?: Partial<FieldGrid> | null;
  fieldKey?: FieldKey | null;
  /** Displaced centre positions from the what-if sandbox, drawn beside the official track. */
  scenarioTrack?: [number, number][] | null;
  /** Keep the current view instead of reframing when data updates. */
  freezeView?: boolean;
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);
}

function coordText(lat: number, lon: number): string {
  return `${Math.abs(lat).toFixed(1)}°${lat >= 0 ? "N" : "S"} ${Math.abs(lon).toFixed(1)}°${
    lon >= 0 ? "E" : "W"
  }`;
}

function stormPopupHtml(s: StormData): string {
  const movement =
    s.movement_dir_deg != null
      ? `${compass(s.movement_dir_deg)} at ${num(s.movement_speed_mph, 0, " mph")}`
      : "stationary";
  return `
    <div style="min-width:190px">
      <strong>${escapeHtml(stormTitle(s))}</strong>
      <div style="margin-top:4px">${num(s.intensity_mph, 0, " mph")} sustained${
        s.category ? ` · Category ${s.category}` : ""
      }</div>
      <div>${num(s.pressure_mb, 0, " mb")} · moving ${movement}</div>
      <div style="margin-top:4px;color:#94a3b8;font-size:12px">
        ${coordText(s.lat, s.lon)}${s.advisory_num ? ` · advisory ${escapeHtml(s.advisory_num)}` : ""}
      </div>
      <div style="margin-top:6px;color:#7dd3fc;font-size:12px">Click for full analysis →</div>
    </div>`;
}

function pointPopupHtml(s: StormData, p: TrackPoint): string {
  return `
    <div style="min-width:170px">
      <strong>${escapeHtml(stormTitle(s))} · ${escapeHtml(p.label)}</strong>
      <div style="margin-top:4px">${escapeHtml(pointTag(p))} · ${num(p.wind_mph, 0, " mph")}${
        p.gust_mph != null ? ` (gusts ${num(p.gust_mph, 0, " mph")})` : ""
      }</div>
      <div style="margin-top:4px;color:#94a3b8;font-size:12px">
        ${p.valid_time ? escapeHtml(fmtFull(p.valid_time)) : ""}<br/>${coordText(p.lat, p.lon)}
      </div>
    </div>`;
}

function coneCollection(storms: StormData[]): FeatureCollection<Polygon> {
  const features: Feature<Polygon>[] = [];
  for (const s of storms) {
    for (const f of s.cone?.features ?? []) {
      features.push({
        type: "Feature",
        properties: {
          storm_id: s.id,
          color: stormColor(s.classification),
          period: (f.properties?.forecast_period_hours as number) ?? 120,
        },
        geometry: f.geometry as Polygon,
      });
    }
  }
  return { type: "FeatureCollection", features };
}

function trackCollection(storms: StormData[]): FeatureCollection<LineString> {
  const features: Feature<LineString>[] = [];
  for (const s of storms) {
    for (const f of s.track?.line.features ?? []) {
      features.push({
        type: "Feature",
        properties: { storm_id: s.id, color: stormColor(s.classification) },
        geometry: f.geometry as LineString,
      });
    }
  }
  return { type: "FeatureCollection", features };
}

export function BasinMap({
  storms,
  focusId = null,
  onSelect,
  height = "440px",
  fieldGrid = null,
  fieldKey = null,
  scenarioTrack = null,
  freezeView = false,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);
  const onSelectRef = useRef(onSelect);
  const [ready, setReady] = useState(false);
  onSelectRef.current = onSelect;

  const visible = useMemo(
    () => (focusId ? storms.filter((s) => s.id === focusId) : storms),
    [storms, focusId],
  );

  // The map is built once and then fed new data, so a five-minute poll never
  // throws away the user's pan and zoom.
  useEffect(() => {
    if (!containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      center: [-70, 24],
      zoom: 2.6,
      attributionControl: { compact: true },
      style: {
        version: 8,
        sources: { ...BASEMAP_SOURCES },
        layers: [BASEMAP_BASE_LAYER],
      },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    mapRef.current = map;

    map.on("load", () => {
      // Added first so the shading sits under the cones and tracks.
      map.addSource("field", {
        type: "image",
        url: blankPng(),
        coordinates: [[-1, 1], [1, 1], [1, -1], [-1, -1]],
      });
      map.addLayer({
        id: "field-raster",
        type: "raster",
        source: "field",
        paint: { "raster-opacity": 0, "raster-fade-duration": 0 },
      });
      // Coastlines and place names go back on top of the shading, so the
      // overlay tells you *where* the environment is favourable.
      map.addLayer(BASEMAP_LABEL_LAYER);
      map.addSource("cones", { type: "geojson", data: EMPTY });
      map.addSource("tracks", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "cone-fill",
        type: "fill",
        source: "cones",
        paint: {
          "fill-color": ["get", "color"],
          "fill-opacity": 0.22,
        },
      });
      map.addLayer({
        id: "cone-outline",
        type: "line",
        source: "cones",
        paint: {
          "line-color": ["get", "color"],
          "line-width": 2,
          "line-opacity": 0.95,
          "line-dasharray": [3, 2],
        },
      });
      map.addLayer({
        id: "track-line",
        type: "line",
        source: "tracks",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#f8fafc", "line-width": 2, "line-opacity": 0.85 },
      });
      map.addSource("scenario", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "scenario-line",
        type: "line",
        source: "scenario",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": "#a78bfa",
          "line-width": 2.4,
          "line-dasharray": [2, 1.5],
        },
      });
      setReady(true);
    });

    return () => {
      setReady(false);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;

    (map.getSource("cones") as maplibregl.GeoJSONSource).setData(coneCollection(visible));
    (map.getSource("tracks") as maplibregl.GeoJSONSource).setData(trackCollection(visible));

    for (const marker of markersRef.current) marker.remove();
    markersRef.current = [];

    const bounds = new maplibregl.LngLatBounds();
    let hasBounds = false;
    const extend = (lon: number, lat: number) => {
      bounds.extend([lon, lat]);
      hasBounds = true;
    };

    for (const s of visible) {
      const color = stormColor(s.classification);

      for (const point of s.track?.points ?? []) {
        extend(point.lon, point.lat);
        if (point.fcst_hour === 0) continue;
        const el = document.createElement("div");
        el.className = "storm-fcst-point";
        el.style.setProperty("--dot", color);
        el.textContent = String(point.fcst_hour);
        if (point.post_tropical) el.dataset.post = "true";
        const popup = new maplibregl.Popup({
          closeButton: false,
          offset: 14,
          className: "storm-popup",
        }).setHTML(pointPopupHtml(s, point));
        const marker = new maplibregl.Marker({ element: el })
          .setLngLat([point.lon, point.lat])
          .setPopup(popup)
          .addTo(map);
        el.addEventListener("mouseenter", () => marker.togglePopup());
        el.addEventListener("mouseleave", () => marker.togglePopup());
        markersRef.current.push(marker);
      }

      if (s.lat == null || s.lon == null) continue;
      extend(s.lon, s.lat);
      const size = markerSize(s.intensity_kt);
      const el = document.createElement("div");
      el.className = "storm-center";
      el.style.setProperty("--dot", color);
      el.style.setProperty("--size", `${size}px`);
      el.setAttribute("role", "button");
      el.setAttribute("aria-label", stormTitle(s));
      const popup = new maplibregl.Popup({
        closeButton: false,
        offset: size / 2 + 6,
        className: "storm-popup",
      }).setHTML(stormPopupHtml(s));
      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([s.lon, s.lat])
        .setPopup(popup)
        .addTo(map);
      el.addEventListener("mouseenter", () => marker.togglePopup());
      el.addEventListener("mouseleave", () => marker.togglePopup());
      el.addEventListener("click", (event) => {
        event.stopPropagation();
        onSelectRef.current?.(s.id);
      });
      markersRef.current.push(marker);
    }

    for (const feature of coneCollection(visible).features) {
      for (const ring of feature.geometry.coordinates) {
        for (const [lon, lat] of ring) extend(lon, lat);
      }
    }

    if (hasBounds && !freezeView) {
      map.fitBounds(bounds, {
        padding: focusId ? 60 : 40,
        maxZoom: focusId ? 5.5 : 4,
        duration: 600,
      });
    }
  }, [ready, visible, focusId, freezeView]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !map.getSource("scenario")) return;
    const source = map.getSource("scenario") as maplibregl.GeoJSONSource;
    source.setData(
      scenarioTrack && scenarioTrack.length > 1
        ? {
            type: "FeatureCollection",
            features: [{
              type: "Feature",
              properties: {},
              geometry: { type: "LineString", coordinates: scenarioTrack },
            }],
          }
        : EMPTY,
    );
  }, [ready, scenarioTrack]);

  // Field shading is redrawn only when the grid or the chosen variable change,
  // so switching layers costs one canvas pass and no network request.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !map.getLayer("field-raster")) return;

    const spec = fieldKey ? FIELD_SPECS[fieldKey] : null;
    const grid =
      fieldGrid?.lats && fieldGrid.lons && fieldGrid.bounds && fieldGrid.fields
        ? (fieldGrid as FieldGrid)
        : null;
    const raster = grid && spec ? renderField(grid, spec) : null;
    if (!raster) {
      map.setPaintProperty("field-raster", "raster-opacity", 0);
      return;
    }
    const source = map.getSource("field") as maplibregl.ImageSource | undefined;
    source?.updateImage({ url: raster.url, coordinates: raster.coordinates });
    // Short of fully opaque so the coastline beneath still reads through the
    // shading; the labels layer above carries the place names.
    map.setPaintProperty("field-raster", "raster-opacity", 0.86);
  }, [ready, fieldGrid, fieldKey]);

  return <div ref={containerRef} className="rounded-lg overflow-hidden" style={{ height }} />;
}
