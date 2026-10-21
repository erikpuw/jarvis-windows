import { defineConfig } from "vite";
import { readFileSync } from "fs";
import path from "path";

export default defineConfig(() => {
  const rootDir = typeof import.meta.dirname !== "undefined" ? path.resolve(import.meta.dirname, "..") : process.cwd();
  // Single version source (README "Quy tắc đánh số"): the repo-root VERSION file.
  const appVersion = readFileSync(path.join(rootDir, "VERSION"), "utf-8").trim();
  return {
    define: {
      __APP_VERSION__: JSON.stringify(appVersion),
    },
    server: {
      // Chỉ loopback: qua proxy này backend luôn thấy IP 127.0.0.1 nên mọi máy vào được 5173 đều né firewall IP.
      // Cần điện thoại/LAN thì chạy `npm run dev -- --host` (tạm thời, biết rõ hệ quả).
      host: "127.0.0.1",
      port: 5173,
      proxy: {
        "/ws": {
          target: "https://127.0.0.1:8340",
          ws: true,
          secure: false,
          changeOrigin: true,
        },
        "/api": {
          target: "https://127.0.0.1:8340",
          secure: false,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: "dist",
      emptyOutDir: true,
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: "three",
              test: /node_modules[\\/]three[\\/]/,
            },
          ],
        },
      },
    },
  },
  };
});
