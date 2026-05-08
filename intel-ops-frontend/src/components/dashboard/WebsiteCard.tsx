import DigestCard from "@/components/shared/DigestCard"
import { useWebsite } from "@/hooks/api/useWebsite"
import { Skeleton } from "@/components/shared/Skeleton"
import { formatCompactNumber } from "@/lib/utils"
import { BASELINE_APP } from "@/types/domain"

/**
 * 总览·网站数据（仅竞品冠军，AF 数据不展示）
 *  · 访问冠军 / 停留冠军 / 全球排名 Top
 */
export default function WebsiteCard() {
  const { data, isLoading } = useWebsite({})
  const rows = data?.website || []
  const competitors = rows.filter((r) => r.competitor !== BASELINE_APP)

  const visitsChamp = [...competitors]
    .filter((r) => r.monthly_visits_num != null)
    .sort((a, b) => (b.monthly_visits_num || 0) - (a.monthly_visits_num || 0))[0]
  const durationChamp = [...competitors]
    .filter((r) => r.avg_visit_duration_sec != null)
    .sort((a, b) => (b.avg_visit_duration_sec || 0) - (a.avg_visit_duration_sec || 0))[0]
  const rankChamp = [...competitors]
    .filter((r) => r.global_rank != null)
    .sort((a, b) => (a.global_rank || Infinity) - (b.global_rank || Infinity))[0]

  const noData = !isLoading && !visitsChamp && !durationChamp && !rankChamp
  if (noData) {
    return (
      <DigestCard
        title="网站数据"
        detailHref="/data/website"
        collapsed
        emptyMsg="暂无 Similarweb 数据"
      />
    )
  }

  return (
    <DigestCard title="网站数据" detailHref="/data/website">
      {isLoading && <Skeleton className="h-16" />}
      {!isLoading && (
        <div className="text-xs">
          {visitsChamp && (
            <div className="flex items-baseline gap-2 py-1 border-b border-border-soft last:border-0">
              <span className="text-muted-foreground text-2xs w-16 shrink-0">访问冠军</span>
              <span className="font-medium truncate flex-1">{visitsChamp.competitor}</span>
              <span className="font-mono tabular-nums">
                {visitsChamp.monthly_visits || formatCompactNumber(visitsChamp.monthly_visits_num)}
              </span>
            </div>
          )}
          {durationChamp && (
            <div className="flex items-baseline gap-2 py-1 border-b border-border-soft last:border-0">
              <span className="text-muted-foreground text-2xs w-16 shrink-0">停留冠军</span>
              <span className="font-medium truncate flex-1">{durationChamp.competitor}</span>
              <span className="font-mono tabular-nums">{durationChamp.avg_visit_duration || "—"}</span>
            </div>
          )}
          {rankChamp && rankChamp.global_rank != null && (
            <div className="flex items-baseline gap-2 py-1">
              <span className="text-muted-foreground text-2xs w-16 shrink-0">全球排名</span>
              <span className="font-medium truncate flex-1">{rankChamp.competitor}</span>
              <span className="font-mono tabular-nums">#{rankChamp.global_rank.toLocaleString()}</span>
            </div>
          )}
        </div>
      )}
    </DigestCard>
  )
}
