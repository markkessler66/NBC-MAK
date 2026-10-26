import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // MapLibre spawns its worker with { type: "module" }, so the emitted worker
  // chunk has to be an ES module rather than Vite's default IIFE.
  worker: { format: "es" },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
