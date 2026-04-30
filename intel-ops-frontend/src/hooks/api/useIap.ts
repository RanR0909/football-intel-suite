import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { IapResponse } from "@/types/api"

interface IapParams {
  competitor?: string
  region?: string
  limit?: number
}

export function useIap(params: IapParams = {}) {
  return useQuery<IapResponse>({
    queryKey: ["iap", params],
    queryFn: async () => {
      const { data } = await api.get("/iap", { params })
      return data
    },
  })
}
