import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import { BASEMAP_BASE_LAYER, BASEMAP_LABEL_LAYER, BASEMAP_SOURCES } from "../lib/basemap";

const RADAR_TILES = "https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913/{z}/{x}/{y}.png";

const radarUrl = () => `${RADAR_TILES}?ts=${Date.now()}`;
const RADAR_OPACITY = 0.8;

interface Props {
  lat: number;
  lon: number;
  label: string;
}

export function RadarMap({ lat, lon, label }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const activeRef = useRef<"a" | "b">("a");
  const radarOnRef = useRef(true);
  const [radarOn, setRadarOn] = useState(true);
  const [refreshedAt, setRefreshedAt] = useState<Date>(new Date());

  useEffect(() => {
    if (!containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      center: [lon, lat],
      zoom: 7.2,
      attributionControl: { compact: true },
      style: {
        version: 8,
        sources: {
          ...BASEMAP_SOURCES,
          // Two radar sources are alternated ("double buffering"): the hidden
          // one loads fresh tiles, then opacities crossfade — no blank flash.
          "radar-a": {
            type: "raster",
            tiles: [radarUrl()],
            tileSize: 256,
            attribution: "NEXRAD composite — Iowa Environmental Mesonet",
          },
          "radar-b": { type: "raster", tiles: [radarUrl()], tileSize: 256 },
        },
        layers: [
          BASEMAP_BASE_LAYER,
          {
            id: "radar-a",
            type: "raster",
            source: "radar-a",
            paint: { "raster-opacity": RADAR_OPACITY, "raster-opacity-transition": { duration: 400 } },
          },
          {
            id: "radar-b",
            type: "raster",
            source: "radar-b",
            paint: { "raster-opacity": 0, "raster-opacity-transition": { duration: 400 } },
          },
          // Above the reflectivity, so heavy echoes cannot hide the towns under them.
          BASEMAP_LABEL_LAYER,
        ],
      },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    new maplibregl.Marker({ color: "#38bdf8" })
      .setLngLat([lon, lat])
      .setPopup(new maplibregl.Popup({ closeButton: false }).setText(label))
      .addTo(map);
    mapRef.current = map;

    // NEXRAD composite refreshes about every 5 minutes.
    const refresh = () => {
      const next = activeRef.current === "a" ? "b" : "a";
      const source = map.getSource(`radar-${next}`) as maplibregl.RasterTileSource | undefined;
      if (!source) return;
      source.setTiles([radarUrl()]);
      map.once("idle", () => {
        if (!mapRef.current) return;
        map.setPaintProperty(`radar-${next}`, "raster-opacity", radarOnRef.current ? RADAR_OPACITY : 0);
        map.setPaintProperty(`radar-${activeRef.current}`, "raster-opacity", 0);
        activeRef.current = next;
        setRefreshedAt(new Date());
      });
    };
    const timer = window.setInterval(refresh, 5 * 60 * 1000);

    return () => {
      clearInterval(timer);
      map.remove();
      mapRef.current = null;
    };
  }, [lat, lon, label]);

  useEffect(() => {
    radarOnRef.current = radarOn;
    const map = mapRef.current;
    if (!map) return;
    const apply = () =>
      map.setPaintProperty(
        `radar-${activeRef.current}`,
        "raster-opacity",
        radarOnRef.current ? RADAR_OPACITY : 0,
      );
    // Style mutations throw if the style hasn't finished loading (mount race).
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [radarOn]);

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="card-title">Radar — NEXRAD Composite</div>
        <div className="flex items-center gap-3">
          <span className="text-[11px] text-slate-500 font-mono">
            tiles refreshed {refreshedAt.toLocaleTimeString()}
          </span>
          <label className="flex items-center gap-1.5 text-xs text-slate-300 cursor-pointer">
            <input
              type="checkbox"
              checked={radarOn}
              onChange={(e) => setRadarOn(e.target.checked)}
              className="accent-sky-500"
            />
            Radar
          </label>
        </div>
      </div>
      <div ref={containerRef} className="h-[420px] rounded-lg overflow-hidden" />
    </div>
  );
}
