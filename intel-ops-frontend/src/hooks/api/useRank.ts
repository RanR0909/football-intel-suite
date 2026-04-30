import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { RankResponse } from "@/types/api"

interface RankParams {
  source?: string
  region?: string
  competitor?: string
  date?: string
  limit?: number
}

export function useRank(params: RankParams = {}) {
  return useQuery<RankResponse>({
    queryKey: ["rankings", params],
    queryFn: async () => {
      const { data } = await api.get("/rank", { params })
      return data
    },
  })
}
