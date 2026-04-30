import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { CommunityResponse } from "@/types/api"

interface CommunityParams {
  source?: "reddit" | "twitter"
  competitor?: string
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
