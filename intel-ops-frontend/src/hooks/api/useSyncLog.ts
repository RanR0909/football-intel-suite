import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { SyncLogResponse } from "@/types/api"

interface Params {
  source?: string
  status?: "success" | "fail" | ""
  limit?: number
}

export function useSyncLog(params: Params = {}) {
  return useQuery<SyncLogResponse>({
    queryKey: ["sync-log", params],
    queryFn: async () => {
      const { data } = await api.get("/sync-log", { params })
      return data
    },
    refetchInterval: 30 * 1000,   // 30s auto-refresh per spec §9.14
  })
}
