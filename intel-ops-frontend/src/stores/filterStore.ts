import { create } from "zustand"
import { persist } from "zustand/middleware"
import type { AppScope } from "@/types/domain"

/**
 * 跨页筛选记忆 — 用户在某页选了"仅 AF"，跳到另一页保持。
 * URL 同步走 useUrlFilters；这里只是兜底。
 */
interface FilterState {
  appScope: AppScope
  setAppScope: (s: AppScope) => void
}

export const useFilterStore = create<FilterState>()(
  persist(
    (set) => ({
      appScope: "competitor",
      setAppScope: (appScope) => set({ appScope }),
    }),
    { name: "intel-ops:filters" }
  )
)
