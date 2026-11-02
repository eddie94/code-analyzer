import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `npm run dev` proxies the API to a running `codemap serve --no-open`.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/codemap/server/static",
    emptyOutDir: true,
    chunkSizeWarningLimit: 2500,
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8700" },
  },
});
