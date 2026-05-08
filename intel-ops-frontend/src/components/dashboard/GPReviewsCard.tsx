import { useMemo } from "react"
import DigestCard from "@/components/shared/DigestCard"
import Pill from "@/components/shared/Pill"
import { useReviewsAggregated } from "@/hooks/api/useAggregated"
import { Skeleton } from "@/components/shared/Skeleton"

/**
 * 总览·GP 评论 — "讨论 Top" 前 3：problems + praise 合并按提及数降序。
 * 跟 GPReviews 页 "讨论 Top" tab 同源同序。
 */
export default function GPReviewsCard() {
  const { data: probs, isLoading: l1 } = useReviewsAggregated("problems", 10)
  const { data: praise, isLoading: l2 } = useReviewsAggregated("praise", 10)
  const isLoading = l1 || l2

  const top3 = useMemo(() => {
    const merged: Array<{
      canonical_id: string
      chinese_name: string | null
      primary_name: string
      total_mentions: number
      kind: "problem" | "praise"
      top_competitor: string | null
    }> = []
    for (const it of probs?.items || []) {
      const top = Object.entries(it.by_competitor || {}).sort((a, b) => b[1] - a[1])[0]
      merged.push({
        canonical_id: it.canonical_id,
        chinese_name: it.chinese_name,
        primary_name: it.primary_name,
        total_mentions: it.total_mentions,
        kind: "problem",
        top_competitor: top?.[0] || null,
      })
    }
    for (const it of praise?.items || []) {
      const top = Object.entries(it.by_competitor || {}).sort((a, b) => b[1] - a[1])[0]
      merged.push({
        canonical_id: it.canonical_id,
        chinese_name: it.chinese_name,
        primary_name: it.primary_name,
        total_mentions: it.total_mentions,
        kind: "praise",
        top_competitor: top?.[0] || null,
      })
    }
    merged.sort((a, b) => b.total_mentions - a.total_mentions)
    return merged.slice(0, 3)
  }, [probs, praise])

  return (
    <DigestCard title="GP 评论" detailHref="/content/gp-reviews?tab=top">
      {isLoading && <Skeleton className="h-20" />}
      {!isLoading && top3.length === 0 && (
        <div className="text-xs text-muted-foreground py-2">暂无聚合主题</div>
      )}
      {top3.length > 0 && (
        <ul className="space-y-2">
          {top3.map((it) => (
            <li key={`${it.kind}:${it.canonical_id}`} className="text-xs">
              <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
                <Pill variant={it.kind === "problem" ? "red" : "green"}>
                  {it.kind === "problem" ? "问题" : "好评"}
                </Pill>
                <span className="font-medium truncate">
                  {it.chinese_name || it.primary_name}
                </span>
                <span className="ml-auto text-2xs text-muted-foreground font-mono tabular-nums">
                  {it.total_mentions} 提及
                </span>
              </div>
              {it.top_competitor && (
                <div className="text-2xs text-muted-foreground pl-2">
                  主要竞品：{it.top_competitor}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </DigestCard>
  )
}
