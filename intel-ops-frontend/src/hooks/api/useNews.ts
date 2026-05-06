import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { NewsResponse, BusinessCategory } from "@/types/api"

interface NewsParams {
  since?: string
  category?: BusinessCategory | ""
  app?: string
  /** 1 (default) | 0 — 只返回 is_business=true 的条目 */
  business_only?: 0 | 1
  limit?: number
}

export function useNews(params: NewsParams = {}) {
  return useQuery<NewsResponse>({
    queryKey: ["news", params],
    queryFn: async () => {
      const { data } = await api.get("/news", { params })
      return data
    },
  })
}
