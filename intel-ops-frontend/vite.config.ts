import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import path from "node:path"

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        // 必须用 127.0.0.1 而非 localhost：node 会优先解析 IPv6 (::1)，
        // python http.server 默认只监听 IPv4 → vite proxy 报 ECONNREFUSED → 浏览器收 500
        target: process.env.VITE_API_BASE || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
})
