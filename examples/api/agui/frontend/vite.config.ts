import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * `npm run build` emits `dist/`, which the Python app serves at `GET /` — same origin as the AG-UI
 * routes, so the browser needs no CORS handling. `npm run dev` instead serves on :5173 with hot reload
 * and proxies `/agui` through to the Python app, so the frontend can be worked on without rebuilding.
 */
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/agui": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
