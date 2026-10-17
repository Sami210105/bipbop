import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The frontend lives in web/ and is built into web/dist, which serve.py serves.
//
//   npm run dev     ->  http://localhost:5173  (hot reload; /api is proxied
//                       to serve.py, so run `python serve.py --no-browser`
//                       in another terminal for songs + AI lookup)
//   npm run build   ->  web/dist               (what serve.py serves)
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
