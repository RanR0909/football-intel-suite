import DigestCard from "@/components/shared/DigestCard"
import { useNews } from "@/hooks/api/useNews"
import { Skeleton } from "@/components/shared/Skeleton"
import { BUSINESS_CATEGORY_LABELS } from "@/types/domain"

/** 总览·商业新闻 — 1 条最新 + 摘要（v2 schema: news_items 表 + AI 字段） */
export default function NewsCard() {
  const { data, isLoading } = useNews({ since: "7d", limit: 5 })
  const items = data?.news || []
  const top = items[0]
  const meta = data ? `近 7d ${data.count} 条命中商业关键词` : "—"

  return (
    <DigestCard title="商业新闻" category="content" detailHref="/content/news" meta={meta}>
      {isLoading && <Skeleton className="h-20" />}
      {!isLoading && !top && (
        <div className="text-xs text-muted-foreground py-3">7d 内无商业新闻</div>
      )}
      {top && (
        <article className="text-xs">
          <div className="flex items-baseline gap-1.5 mb-1">
            <span className="font-medium">{top.app_name || "—"}</span>
            <span className="text-2xs text-muted-foreground">{top.source}</span>
            {top.business_category && (
              <span className="text-2xs text-pill-amber-fg bg-pill-amber-bg px-1 rounded">
                {BUSINESS_CATEGORY_LABELS[top.business_category]}
              </span>
            )}
            {!top.business_category && top.is_business && (
              <span className="text-2xs text-pill-amber-fg bg-pill-amber-bg px-1 rounded">⭐ biz</span>
            )}
          </div>
          <a
            href={top.url}
            target="_blank"
            rel="noreferrer"
            className="font-medium hover:text-brand-700 leading-snug line-clamp-2"
          >
            {top.title}
          </a>
          {top.snippet && (
            <p className="mt-1 text-2xs text-muted-foreground line-clamp-2 leading-snug">
              {top.snippet}
            </p>
          )}
        </article>
      )}
    </DigestCard>
  )
}
