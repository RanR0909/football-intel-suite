import DigestCard from "@/components/shared/DigestCard"
import { useWebsite } from "@/hooks/api/useWebsite"
import { Skeleton } from "@/components/shared/Skeleton"
import { formatCompactNumber, formatPct } from "@/lib/utils"
import { BASELINE_APP } from "@/types/domain"

/** 总览·网站数据 — AF 4 核心指标 + 竞品 Top 1（按月访问量）*/
export default function WebsiteCard() {
  const { data, isLoading } = useWebsite({})
  const rows = data?.website || []
  const af = rows.find((r) => r.competitor === BASELINE_APP)
  const competitors = rows.filter((r) => r.competitor !== BASELINE_APP)
  const top = [...competitors].sort(
    (a, b) => (b.monthly_visits_num || 0) - (a.monthly_visits_num || 0)
  )[0]

  return (
    <DigestCard
      title="网站数据"
      category="data"
      detailHref="/data/website"
      meta={af ? `${af.snapshot_month} · Similarweb` : "—"}
    >
      {isLoading && <Skeleton className="h-20" />}
      {!isLoading && af && (
        <div className="text-xs space-y-1">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <div className="text-2xs text-muted-foreground">月访问</div>
              <div className="font-mono tabular-nums">
                {af.monthly_visits || formatCompactNumber(af.monthly_visits_num)}
              </div>
            </div>
            <div>
              <div className="text-2xs text-muted-foreground">平均停留</div>
              <div className="font-mono tabular-nums">{af.avg_visit_duration || "—"}</div>
            </div>
            <div>
              <div className="text-2xs text-muted-foreground">跳出率</div>
              <div className="font-mono tabular-nums">{formatPct(af.bounce_rate)}</div>
            </div>
            <div>
              <div className="text-2xs text-muted-foreground">全球排名</div>
              <div className="font-mono tabular-nums">
                {af.global_rank != null ? `#${af.global_rank.toLocaleString()}` : "—"}
              </div>
            </div>
          </div>
          {top && (
            <>
              <div className="h-px bg-border-soft my-1" />
              <div className="flex items-center gap-2">
                <span className="text-2xs text-muted-foreground w-16 shrink-0">竞品 Top1</span>
                <span className="font-medium truncate">{top.competitor}</span>
                <span className="ml-auto font-mono tabular-nums">
                  {top.monthly_visits || formatCompactNumber(top.monthly_visits_num)}
                </span>
              </div>
            </>
          )}
        </div>
      )}
      {!isLoading && !af && (
        <div className="text-xs text-muted-foreground py-3">暂无 AF 网站数据</div>
      )}
    </DigestCard>
  )
}
