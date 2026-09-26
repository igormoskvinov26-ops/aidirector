import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Время сборки в МСК — по нему на экране ошибки видно, дошло ли обновление.
  define: {
    __BUILD__: JSON.stringify(
      new Date().toLocaleString("ru-RU", { timeZone: "Europe/Moscow" })
    ),
  },
  server: {
    port: 3000,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  build: {
    // Split the chart library out of the app bundle: it rarely changes, so
    // browsers can keep it cached across deploys instead of re-downloading
    // 600 kB every time a label is edited.
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (!id.includes("node_modules")) return;
          if (id.includes("recharts") || id.includes("d3-")) return "charts";
          if (id.includes("react-dom") || id.includes("/react/")) return "react";
        },
      },
    },
    chunkSizeWarningLimit: 700,
  },
});
