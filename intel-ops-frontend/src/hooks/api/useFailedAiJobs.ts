import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { FailedAiJobsResponse } from "@/types/api"

interface Params {
  resolved?: "true" | "false"
  task?: string
  latest_round?: boolean
  limit?: number
}

export function useFailedAiJobs(params: Params = {}) {
  return useQuery<FailedAiJobsResponse>({
    queryKey: ["failed-ai-jobs", params],
    queryFn: async () => {
      const { data } = await api.get("/failed-ai-jobs", { params })
      return data
    },
  })
}

export function useRetryAiJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) => {
      const { data } = await api.post(`/failed-ai-jobs/${id}/retry`)
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["failed-ai-jobs"] })
    },
  })
}
