import DigestCard from "@/components/shared/DigestCard"
import { useRank } from "@/hooks/api/useRank"
import { Skeleton } from "@/components/shared/Skeleton"
import { formatCompactNumber, cn } from "@/lib/utils"
import { BASELINE_APP } from "@/types/domain"

/**
 * 总览·收入下载（仅竞品冠军，AF 数据不展示）
 *  · 收入冠军 / 下载冠军 / 7d 涨幅冠军
 */
export default function RevenueCard() {
  const { data: snap, isLoading } = useRank({
    source: "sensor_tower", platform: "ios", region: "us", limit: 100,
  })
  const rows = snap?.rankings || []
  const competitors = rows.filter((r) => r.competitor && r.competitor !== BASELINE_APP)

  const revenueChamp = [...competitors]
    .filter((r) => r.revenue_num != null)
    .sort((a, b) => (b.revenue_num || 0) - (a.revenue_num || 0))[0]
  const downloadChamp = [...competitors]
    .filter((r) => r.downloads_num != null)
    .sort((a, b) => (b.downloads_num || 0) - (a.downloads_num || 0))[0]
  const moverChamp = [...competitors]
    .filter((r) => r.delta != null && r.delta < 0)  // delta < 0 = 排名上升
    .sort((a, b) => (a.delta || 0) - (b.delta || 0))[0]

  const noData = !isLoading && !revenueChamp && !downloadChamp && !moverChamp
  if (noData) {
    return (
      <DigestCard
        title="收入下载"
        detailHref="/data/revenue"
        collapsed
        emptyMsg="暂无榜单数据"
      />
    )
  }

  return (
    <DigestCard title="收入下载" detailHref="/data/revenue">
      {isLoading && <Skeleton className="h-16" />}
      {!isLoading && (
        <div className="text-xs">
          {revenueChamp && (
            <div className="flex items-baseline gap-2 py-1 border-b border-border-soft last:border-0">
              <span className="text-muted-foreground text-2xs w-16 shrink-0">收入冠军</span>
              <span className="font-medium truncate flex-1">{revenueChamp.competitor}</span>
              <span className="font-mono tabular-nums">${formatCompactNumber(revenueChamp.revenue_num)}</span>
            </div>
          )}
          {downloadChamp && (
            <div className="flex items-baseline gap-2 py-1 border-b border-border-soft last:border-0">
              <span className="text-muted-foreground text-2xs w-16 shrink-0">下载冠军</span>
              <span className="font-medium truncate flex-1">{downloadChamp.competitor}</span>
              <span className="font-mono tabular-nums">{formatCompactNumber(downloadChamp.downloads_num)}</span>
            </div>
          )}
          {moverChamp && moverChamp.delta != null && (
            <div className="flex items-baseline gap-2 py-1">
              <span className="text-muted-foreground text-2xs w-16 shrink-0">7d 涨幅</span>
              <span className="font-medium truncate flex-1">{moverChamp.competitor}</span>
              <span className={cn(
                "font-mono tabular-nums",
                moverChamp.delta < 0 ? "text-semantic-success" : "text-semantic-danger"
              )}>
                {moverChamp.delta > 0 ? "↓" : "↑"} {Math.abs(moverChamp.delta)} 名
              </span>
            </div>
          )}
        </div>
      )}
    </DigestCard>
  )
}
