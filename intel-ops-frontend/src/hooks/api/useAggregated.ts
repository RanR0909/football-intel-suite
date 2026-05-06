/** Aggregated content endpoints (spec §4.2):
 *   /api/reviews/aggregated         — by entity (problems / praise / localization / churn)
 *   /api/community-posts/aggregated — by topic / player / league / competitor
 *   /api/ads/aggregated             — by selling_point / region / competitor
 */
import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type {
  ReviewsAggregatedResponse, ReviewsAggregatedTab,
  CommunityAggregatedResponse, CommunityAggregatedDim,
  AdsAggregatedResponse, AdsAggregatedDim,
} from "@/types/api"

export function useReviewsAggregated(tab: ReviewsAggregatedTab, limit = 50) {
  return useQuery<ReviewsAggregatedResponse>({
    queryKey: ["reviews-aggregated", { tab, limit }],
    queryFn: async () => {
      const { data } = await api.get("/reviews/aggregated", {
        params: { tab, limit },
      })
      return data
    },
  })
}

export function useCommunityAggregated(dim: CommunityAggregatedDim,
                                       opts: { since?: string; limit?: number } = {}) {
  return useQuery<CommunityAggregatedResponse>({
    queryKey: ["community-aggregated", { dim, ...opts }],
    queryFn: async () => {
      const { data } = await api.get("/community-posts/aggregated", {
        params: { dim, ...opts },
      })
      return data
    },
  })
}

export function useAdsAggregated(dim: AdsAggregatedDim, limit = 50) {
  return useQuery<AdsAggregatedResponse>({
    queryKey: ["ads-aggregated", { dim, limit }],
    queryFn: async () => {
      const { data } = await api.get("/ads/aggregated", {
        params: { dim, limit },
      })
      return data
    },
  })
}
