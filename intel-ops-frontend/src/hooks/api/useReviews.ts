import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { ReviewsResponse } from "@/types/api"

interface ReviewsParams {
  competitor?: string
  label?: string
  region?: string
  since?: string
  limit?: number
}

export function useReviews(params: ReviewsParams = {}) {
  return useQuery<ReviewsResponse>({
    queryKey: ["reviews", params],
    queryFn: async () => {
      const { data } = await api.get("/reviews", { params })
      return data
    },
  })
}
