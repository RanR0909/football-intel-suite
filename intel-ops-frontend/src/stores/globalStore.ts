import { create } from "zustand"
import { persist } from "zustand/middleware"

interface GlobalState {
  sidebarCollapsed: boolean
  theme: "light" | "dark" | "system"
  toggleSidebar: () => void
  setTheme: (t: "light" | "dark" | "system") => void
}

export const useGlobalStore = create<GlobalState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      theme: "system",
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setTheme: (theme) => {
        set({ theme })
        applyTheme(theme)
      },
    }),
    { name: "intel-ops:global" }
  )
)

function applyTheme(theme: "light" | "dark" | "system") {
  const root = document.documentElement
  if (theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches)) {
    root.classList.add("dark")
  } else {
    root.classList.remove("dark")
  }
}

// 初次加载时应用主题
if (typeof window !== "undefined") {
  const saved = useGlobalStore.getState().theme
  applyTheme(saved)
}
