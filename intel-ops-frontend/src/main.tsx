import React from "react"
import ReactDOM from "react-dom/client"
import "./index.css"
import App from "./App"

async function bootstrap() {
  // 开发模式可选启用 MSW（默认关，依赖真实后端 API）
  // 改 .env.local 或这里：if (import.meta.env.DEV && import.meta.env.VITE_USE_MOCK)
  if (import.meta.env.DEV && import.meta.env.VITE_USE_MOCK === "1") {
    const { worker } = await import("./mocks/browser")
    await worker.start({ onUnhandledRequest: "bypass" })
  }

  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  )
}

bootstrap()
