import DigestCard from "@/components/shared/DigestCard"
import Pill from "@/components/shared/Pill"
import { useReviews } from "@/hooks/api/useReviews"
import { Skeleton } from "@/components/shared/Skeleton"
import { REVIEW_LABEL_DISPLAY } from "@/types/domain"
import type { ReviewLabel } from "@/types/api"

/** 总览·GP 评论 — 3 条代表性（含翻译 + 标签）*/
export default function GPReviewsCard() {
  const { data, isLoading } = useReviews({ since: "3d", limit: 6 })
  const rows = (data?.reviews || []).slice(0, 3)
  const meta = data ? `近 3d 已标 ${data.count} 条` : "—"

  return (
    <DigestCard title="GP 评论" category="content" detailHref="/content/gp-reviews" meta={meta}>
      {isLoading && <Skeleton className="h-20" />}
      {!isLoading && rows.length === 0 && (
        <div className="text-xs text-muted-foreground py-3">暂无已标评论</div>
      )}
      {rows.length > 0 && (
        <ul className="space-y-2">
          {rows.map((r) => {
            const labelMeta = r.label ? REVIEW_LABEL_DISPLAY[r.label as ReviewLabel] : null
            const variant = labelMeta?.color.replace("pill-", "") as
              | "purple" | "teal" | "amber" | "blue" | "pink" | "red" | "green" | "gray"
              | undefined
            const text = r.translated_text || r.content || ""
            return (
              <li key={r.id} className="text-xs">
                <div className="flex items-center gap-1.5 mb-0.5">
                  {labelMeta && variant && (
                    <Pill variant={variant}>{labelMeta.text}</Pill>
                  )}
                  <span className="text-2xs text-muted-foreground">
                    {r.competitor} · {r.region_code}
                    {r.score != null && ` · ${r.score}★`}
                  </span>
                </div>
                <div className="line-clamp-2 leading-snug">
                  {text}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </DigestCard>
  )
}
