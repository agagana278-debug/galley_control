import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on("error", (_err, _req, res) => {
            if (!res.headersSent) {
              res.writeHead(503, { "Content-Type": "application/json" });
            }
            res.end(
              JSON.stringify({
                detail:
                  "FastAPI backend is not reachable at http://127.0.0.1:8000. Run start_galley_control.bat or start uvicorn on port 8000.",
              })
            );
          });
        },
      },
    },
  },
});
