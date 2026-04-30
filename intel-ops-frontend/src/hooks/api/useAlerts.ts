import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { AlertsResponse } from "@/types/api"

interface AlertsParams {
  status?: string
  type?: string
  severity?: string
  since?: string
  limit?: number
}

export function useAlerts(params: AlertsParams = {}) {
  return useQuery<AlertsResponse>({
    queryKey: ["alerts", params],
    queryFn: async () => {
      const { data } = await api.get("/alerts", { params })
      return data
    },
  })
}

export function useAckAlert() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) => {
      const { data } = await api.post(`/alerts/${id}/ack`)
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alerts"] })
    },
  })
}
