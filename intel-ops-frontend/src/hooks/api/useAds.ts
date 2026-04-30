import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { AdsResponse } from "@/types/api"

interface AdsParams {
  competitor?: string
  country?: string
  limit?: number
}

export function useAds(params: AdsParams = {}) {
  return useQuery<AdsResponse>({
    queryKey: ["ads", params],
    queryFn: async () => {
      const { data } = await api.get("/ads", { params })
      return data
    },
  })
}
