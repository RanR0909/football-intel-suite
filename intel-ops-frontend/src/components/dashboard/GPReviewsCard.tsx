import DigestCard from "@/components/shared/DigestCard"
import Pill from "@/components/shared/Pill"
import { useReviews } from "@/hooks/api/useReviews"
import { Skeleton } from "@/components/shared/Skeleton"
import { REVIEW_LABEL_DISPLAY } from "@/types/domain"
import type { ReviewLabel } from "@/types/api"

function relTime(s: string | null): string {
  if (!s) return ""
  const d = new Date(s)
  if (!Number.isFinite(d.valueOf())) return ""
  const h = Math.floor((Date.now() - d.valueOf()) / 3600_000)
  if (h < 1) return "刚刚"
  if (h < 24) return `${h}h`
  return `${Math.floor(h / 24)}d`
}

/** 总览·GP 评论 — 3 条带标签的代表性评论 */
export default function GPReviewsCard() {
  const { data, isLoading } = useReviews({ since: "3d", limit: 8 })
  const rows = (data?.reviews || []).slice(0, 3)

  return (
    <DigestCard title="GP 评论" detailHref="/content/gp-reviews">
      {isLoading && <Skeleton className="h-20" />}
      {!isLoading && rows.length === 0 && (
        <div className="text-xs text-muted-foreground py-2">暂无已标评论</div>
      )}
      {rows.length > 0 && (
        <ul className="space-y-2">
          {rows.map((r) => {
            const labelMeta = r.label ? REVIEW_LABEL_DISPLAY[r.label as ReviewLabel] : null
            const variant = labelMeta?.color.replace("pill-", "") as
              | "purple" | "teal" | "amber" | "blue" | "pink" | "red" | "green" | "gray"
              | undefined
            const text = r.translated_text || r.content || ""
            const region = (r.region_code || "").toUpperCase()
            return (
              <li key={r.id} className="text-xs">
                <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
                  <span className="font-medium">{r.competitor}</span>
                  {labelMeta && variant && <Pill variant={variant}>{labelMeta.text}</Pill>}
                  {region && <Pill variant="gray">{region}</Pill>}
                  {r.score != null && (
                    <span className="text-2xs text-muted-foreground font-mono tabular-nums">
                      {"★".repeat(r.score)}{"☆".repeat(5 - r.score)}
                    </span>
                  )}
                  <span className="ml-auto text-2xs text-muted-foreground font-mono tabular-nums">
                    {relTime(r.at)}
                  </span>
                </div>
                <div className="line-clamp-2 leading-snug">{text}</div>
              </li>
            )
          })}
        </ul>
      )}
    </DigestCard>
  )
}
