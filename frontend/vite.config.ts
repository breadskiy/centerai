import { defineConfig } from "vite";
import tailwind from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react(), tailwind()],
  server: { host: "127.0.0.1", proxy: { "/api": "http://127.0.0.1:8000" } },
});
