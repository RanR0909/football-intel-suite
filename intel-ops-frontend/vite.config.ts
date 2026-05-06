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
    // 同时监听 IPv4 + IPv6（dual-stack）：
    //   - "127.0.0.1" 只监听 IPv4 → 浏览器走 localhost 解析 [::1] 时连不上
    //   - "::"        IPv6 socket 同时接受 IPv4-mapped 请求（macOS/Linux 默认）
    //   - dashboard_server 在 127.0.0.1:8899（IPv4），proxy target 已写死 IPv4 不受影响
    host: "::",
    port: 5173,
    strictPort: true,        // 端口被占就直接失败，避免静悄悄换端口
    proxy: {
      "/api": {
        // 必须用 127.0.0.1 而非 localhost：node 18 默认 DNS 优先 IPv6 (::1)，
        // 而 dashboard_server 默认绑 127.0.0.1 → vite proxy 报 ECONNREFUSED → 浏览器收 500
        target: process.env.VITE_API_BASE || "http://127.0.0.1:8899",
        changeOrigin: true,
      },
    },
  },
})
