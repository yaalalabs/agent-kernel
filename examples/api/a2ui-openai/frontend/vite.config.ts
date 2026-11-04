import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The agent runs on :8000. Proxying keeps the browser on one origin, so there is no CORS to
// configure and `fetch("/api/v1/chat")` in App.tsx needs no base URL.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
