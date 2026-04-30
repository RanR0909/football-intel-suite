import DigestCard from "@/components/shared/DigestCard"
import { useRank } from "@/hooks/api/useRank"
import { Skeleton } from "@/components/shared/Skeleton"
import { formatCompactNumber, cn } from "@/lib/utils"
import { BASELINE_APP } from "@/types/domain"

/**
 * 总览·收入下载
 * - AF 自家两个核心数（最近月下载 / 收入）
 * - 9 竞品里 月收入冠军 + 7d 涨幅冠军
 */
export default function RevenueCard() {
  const { data: snap, isLoading } = useRank({
    source: "sensor_tower", region: "us", limit: 100,
  })
  const rows = snap?.rankings || []

  const af = rows.find((r) => r.competitor === BASELINE_APP)
  const competitors = rows.filter((r) => r.competitor && r.competitor !== BASELINE_APP)

  // 收入冠军 = revenue_num 最大
  const revenueChamp = [...competitors].sort(
    (a, b) => (b.revenue_num || 0) - (a.revenue_num || 0)
  )[0]
  // 7d 涨幅冠军 = delta（rank 提升越大越好；数小=好）取负值最大
  const moverChamp = [...competitors]
    .filter((r) => r.delta != null)
    .sort((a, b) => (a.delta || 0) - (b.delta || 0))[0]

  return (
    <DigestCard
      title="收入下载"
      category="data"
      detailHref="/data/revenue"
      meta={af ? `美区 · sensor_tower 估算` : "—"}
    >
      {isLoading && <Skeleton className="h-20" />}
      {!isLoading && (
        <div className="space-y-1 text-xs">
          {/* AF 两行 */}
          <div className="flex items-center gap-2 py-1">
            <span className="font-medium text-semantic-info w-20 truncate">{BASELINE_APP}</span>
            <span className="text-muted-foreground">月下载</span>
            <span className="ml-auto tabular-nums font-mono">
              {af?.downloads_num != null ? formatCompactNumber(af.downloads_num) : "—"}
            </span>
          </div>
          <div className="flex items-center gap-2 py-1">
            <span className="font-medium text-semantic-info w-20 truncate">{BASELINE_APP}</span>
            <span className="text-muted-foreground">月收入</span>
            <span className="ml-auto tabular-nums font-mono">
              ${af?.revenue_num != null ? formatCompactNumber(af.revenue_num) : "—"}
            </span>
          </div>
          {/* divider */}
          <div className="h-px bg-border-soft my-1" />
          {revenueChamp && (
            <div className="flex items-center gap-2 py-1">
              <span className="text-muted-foreground w-20 shrink-0">收入冠军</span>
              <span className="font-medium truncate">{revenueChamp.competitor}</span>
              <span className="ml-auto tabular-nums font-mono">
                ${formatCompactNumber(revenueChamp.revenue_num)}
              </span>
            </div>
          )}
          {moverChamp && moverChamp.delta != null && (
            <div className="flex items-center gap-2 py-1">
              <span className="text-muted-foreground w-20 shrink-0">7d 涨幅</span>
              <span className="font-medium truncate">{moverChamp.competitor}</span>
              <span className={cn(
                "ml-auto tabular-nums",
                moverChamp.delta < 0 ? "text-semantic-danger" : "text-semantic-success"
              )}>
                {moverChamp.delta > 0 ? "+" : ""}{moverChamp.delta} 名
              </span>
            </div>
          )}
        </div>
      )}
    </DigestCard>
  )
}
