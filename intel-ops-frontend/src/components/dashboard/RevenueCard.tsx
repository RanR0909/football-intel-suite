import DigestCard from "@/components/shared/DigestCard"
import { useRank } from "@/hooks/api/useRank"
import { Skeleton } from "@/components/shared/Skeleton"
import { formatCompactNumber, cn } from "@/lib/utils"
import { BASELINE_APP } from "@/types/domain"

/**
 * 总览·收入下载（仅竞品冠军，AF 数据不展示）
 *  · 收入冠军 / 下载冠军 / 7d 涨幅冠军
 *
 * 在内容主视图（占双列）下用 3-col 横排；在数据副视图下用单列堆叠。
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
    .filter((r) => r.delta != null && r.delta < 0)
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
    <DigestCard title="收入下载" detailHref="/data/revenue" className="col-span-2">
      {isLoading && <Skeleton className="h-16" />}
      {!isLoading && (
        <div className="grid grid-cols-3 gap-x-6 gap-y-1 text-xs">
          <ChampionCell label="收入冠军" name={revenueChamp?.competitor} value={
            revenueChamp ? `$${formatCompactNumber(revenueChamp.revenue_num)}` : null
          } />
          <ChampionCell label="下载冠军" name={downloadChamp?.competitor} value={
            downloadChamp ? formatCompactNumber(downloadChamp.downloads_num) : null
          } />
          <ChampionCell
            label="7d 涨幅"
            name={moverChamp?.competitor}
            value={
              moverChamp && moverChamp.delta != null
                ? `${moverChamp.delta > 0 ? "↓" : "↑"} ${Math.abs(moverChamp.delta)} 名`
                : null
            }
            valueClass={moverChamp && moverChamp.delta != null && moverChamp.delta < 0
              ? "text-semantic-success"
              : "text-semantic-danger"
            }
          />
        </div>
      )}
    </DigestCard>
  )
}

function ChampionCell({ label, name, value, valueClass }: {
  label: string;
  name: string | null | undefined;
  value: string | null | undefined;
  valueClass?: string;
}) {
  return (
    <div>
      <div className="text-2xs text-muted-foreground mb-1">{label}</div>
      {name ? (
        <>
          <div className="font-medium truncate">{name}</div>
          <div className={cn("font-mono tabular-nums text-2xs mt-0.5", valueClass)}>
            {value}
          </div>
        </>
      ) : (
        <div className="text-muted-foreground">—</div>
      )}
    </div>
  )
}
