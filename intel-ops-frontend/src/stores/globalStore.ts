import { create } from "zustand"
import { persist } from "zustand/middleware"

interface GlobalState {
  sidebarCollapsed: boolean
  toggleSidebar: () => void
}

export const useGlobalStore = create<GlobalState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
    }),
    { name: "intel-ops:global" }
  )
)
