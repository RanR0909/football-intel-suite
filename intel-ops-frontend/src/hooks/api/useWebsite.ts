import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { WebsiteResponse } from "@/types/api"

interface WebsiteParams {
  competitor?: string
  month?: string
}

export function useWebsite(params: WebsiteParams = {}) {
  return useQuery<WebsiteResponse>({
    queryKey: ["website", params],
    queryFn: async () => {
      const { data } = await api.get("/website", { params })
      return data
    },
  })
}
