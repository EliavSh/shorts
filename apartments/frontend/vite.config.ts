import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  // Served under /apartments/ inside the unified shorts dashboard, so all asset
  // URLs must be prefixed. The API client base URL is set separately via
  // VITE_API_URL=/apartments/api at build time (see api/client.ts).
  base: "/apartments/",
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
