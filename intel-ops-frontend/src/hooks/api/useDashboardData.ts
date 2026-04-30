import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"

export function useDashboardData() {
  return useQuery({
    queryKey: ["dashboard"],
    queryFn: async () => {
      const { data } = await api.get("/data/dashboard_data")
      return data
    },
  })
}

export function useStatus() {
  return useQuery({
    queryKey: ["status"],
    queryFn: async () => {
      const { data } = await api.get("/status")
      return data
    },
    refetchInterval: 30 * 1000,  // 30s 轮询
  })
}
