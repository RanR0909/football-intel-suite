import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { NewsResponse } from "@/types/api"

interface NewsParams {
  since?: string
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
