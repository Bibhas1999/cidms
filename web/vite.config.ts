import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// Development: open http://supreme.localhost:5173 (a client) or http://admin.localhost:5173 (the platform).
// API calls go to FastAPI on :8000 with the browser's Host header kept, so the server knows which client it is
// and the session cookie stays on this address.
export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 5173,
    strictPort: true,
    allowedHosts: [".localhost"],
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: false },
      "/healthz": { target: "http://localhost:8000", changeOrigin: false },
      "/viewer": { target: "http://localhost:8000", changeOrigin: false },  // the image viewer, through the app
    },
  },
  build: { outDir: "dist", emptyOutDir: true, sourcemap: true },
});
