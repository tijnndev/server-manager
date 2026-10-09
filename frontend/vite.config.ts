import { cpSync, createReadStream, existsSync, statSync } from "node:fs";
import { extname, join, normalize, resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const monacoSrc = resolve("node_modules/monaco-editor/min/vs");

function monacoAssets(): Plugin {
  const types: Record<string, string> = {
    ".js": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".ttf": "font/ttf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".svg": "image/svg+xml",
    ".html": "text/html",
  };
  return {
    name: "monaco-assets",
    configureServer(server) {
      server.middlewares.use("/monaco/vs", (req, res, next) => {
        const url = decodeURIComponent((req.url ?? "/").split("?")[0]);
        const file = normalize(join(monacoSrc, url));
        if (!file.startsWith(monacoSrc) || !existsSync(file) || statSync(file).isDirectory()) {
          next();
          return;
        }
        res.setHeader("Content-Type", types[extname(file)] ?? "application/octet-stream");
        createReadStream(file).pipe(res);
      });
    },
    writeBundle(options) {
      const dir = options.dir ?? resolve("dist");
      cpSync(monacoSrc, join(dir, "monaco/vs"), { recursive: true });
    },
  };
}

export default defineConfig({
  plugins: [react(), monacoAssets()],
  server: {
    port: 5174,
    proxy: {
      "/api": { target: "http://127.0.0.1:7101", ws: true },
    },
  },
});
