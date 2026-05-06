import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { VersionsResponse, VersionRelatedReviewsResponse } from "@/types/api"

interface VersionsParams {
  competitor?: string
  since?: string
  limit?: number
}

export function useVersions(params: VersionsParams = {}) {
  return useQuery<VersionsResponse>({
    queryKey: ["versions", params],
    queryFn: async () => {
      const { data } = await api.get("/versions", { params })
      return data
    },
  })
}

export function useVersionRelatedReviews(versionId: number | null) {
  return useQuery<VersionRelatedReviewsResponse>({
    queryKey: ["version-related", versionId],
    enabled: versionId != null,
    queryFn: async () => {
      const { data } = await api.get(`/versions/${versionId}/related-reviews`)
      return data
    },
  })
}
