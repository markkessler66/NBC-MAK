const CARTO_KEY = import.meta.env.VITE_CARTO_KEY?.trim() ?? "";
const CARTO_QS = CARTO_KEY ? `?key=${encodeURIComponent(CARTO_KEY)}` : "";

const tiles = (variant: string) =>
  ["a", "b", "c", "d"].map(
    (s) => `https://${s}.basemaps.cartocdn.com/${variant}/{z}/{x}/{y}.png${CARTO_QS}`,
  );

// Terrain and labels are separate layers so a data overlay can sit between
// them: shading the ocean should not cost you the place names.
export const BASEMAP_SOURCES = {
  "carto-dark": {
    type: "raster" as const,
    tiles: tiles("dark_nolabels"),
    tileSize: 256,
    attribution: "© OpenStreetMap contributors © CARTO",
  },
  "carto-dark-labels": {
    type: "raster" as const,
    tiles: tiles("dark_only_labels"),
    tileSize: 256,
  },
};

export const BASEMAP_BASE_LAYER = { id: "basemap", type: "raster" as const, source: "carto-dark" };

/** Add above any overlay that would otherwise bury the basemap's labels. */
export const BASEMAP_LABEL_LAYER = {
  id: "basemap-labels",
  type: "raster" as const,
  source: "carto-dark-labels",
};
