import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { CommunityResponse } from "@/types/api"

interface CommunityParams {
  source?: "reddit" | "twitter"
  competitor?: string
  /** 时间窗口：24h / 7d / 30d / ISO 时间戳 — 后端在 dashboard_server.py _parse_since 处理 */
  since?: string
  limit?: number
}

export function useCommunity(params: CommunityParams = {}) {
  return useQuery<CommunityResponse>({
    queryKey: ["community", params],
    queryFn: async () => {
      const { data } = await api.get("/community", { params })
      return data
    },
  })
}
