import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/static/blackhole-hero/",
  plugins: [react()],
  build: {
    outDir: resolve(__dirname, "../../static/blackhole-hero"),
    emptyOutDir: true,
    manifest: "manifest.json",
    rollupOptions: { input: resolve(__dirname, "src/main.tsx") },
  },
});
