import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { CandidatesResponse } from "@/types/api"

interface CandidatesParams {
  topic?: string
  conf_min?: number
  limit?: number
}

export function useCandidates(params: CandidatesParams = {}) {
  return useQuery<CandidatesResponse>({
    queryKey: ["candidates", params],
    queryFn: async () => {
      const { data } = await api.get("/candidates", { params })
      return data
    },
  })
}
