import { setWorkerUrl } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

// MapLibre 6 derives its worker URL at runtime from the bundle's own
// import.meta.url, which no bundler can see statically, so the worker chunk is
// never emitted and the request 404s. Nothing throws: raster tiles and DOM
// markers keep working while every GeoJSON source silently fails to tile.
// Point MapLibre at the worker Vite actually emitted.
setWorkerUrl(workerUrl);
