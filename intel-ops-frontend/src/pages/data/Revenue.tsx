import { useMemo, useState } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import RegionChip from "@/components/shared/RegionChip"
import BaselineToggle from "@/components/shared/BaselineToggle"
import BaselineDeltaCell from "@/components/shared/BaselineDeltaCell"
import EmptyState from "@/components/shared/EmptyState"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useRank } from "@/hooks/api/useRank"
import { useUrlFilters } from "@/hooks/useUrlFilters"
import { computeNumericDelta } from "@/lib/baseline"
import { formatCompactNumber } from "@/lib/utils"
import { BASELINE_APP } from "@/types/domain"

export default function Revenue() {
  const { value, setValue } = useUrlFilters({ region: "us" })
  const [showBaseline, setShowBaseline] = useState(true)
  const region = value("region")

  const { data, isLoading, isError, refetch } = useRank({
    source: "sensor_tower", region, limit: 100,
  })
  const rows = data?.rankings || []

  const af = rows.find((r) => r.competitor === BASELINE_APP)
  const others = useMemo(
    () => rows.filter((r) => r.competitor && r.competitor !== BASELINE_APP)
      .sort((a, b) => (b.revenue_num || 0) - (a.revenue_num || 0)),
    [rows]
  )

  return (
    <div>
      <PageHeader
        title="收入下载"
        subtitle="以 AF 为基准对比所有竞品（数据源：Sensor Tower 月估算）"
      />

      <KpiRow>
        <KpiCard
          label="AF 月下载"
          value={af?.downloads_num != null ? formatCompactNumber(af.downloads_num) : "—"}
          hint={`${region.toUpperCase()} 区`}
        />
        <KpiCard
          label="AF 月收入"
          value={af?.revenue_num != null ? "$" + formatCompactNumber(af.revenue_num) : "—"}
          hint={`${region.toUpperCase()} 区`}
        />
        <KpiCard
          label="AF 排名"
          value={af?.rank_value != null ? `#${af.rank_value}` : "—"}
          hint="体育榜"
        />
        <KpiCard
          label="数据完整度"
          value={`${others.filter((r) => r.revenue_num != null).length}/${others.length}`}
          hint="竞品有收入数据的"
        />
      </KpiRow>

      <div className="space-y-2 mb-3">
        <RegionChip value={region} onChange={(v) => setValue("region", v)} />
        <div className="flex justify-end">
          <BaselineToggle show={showBaseline} onChange={setShowBaseline} />
        </div>
      </div>

      {isLoading && <SkeletonTable rows={10} />}
      {isError && <EmptyState type="error" onRetry={() => refetch()} />}
      {!isLoading && !isError && rows.length === 0 && <EmptyState type="empty" />}

      {rows.length > 0 && (
        <div className="border border-border-soft rounded-md bg-card overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-muted/30">
              <tr className="text-2xs uppercase tracking-wider text-muted-foreground">
                <th className="text-left px-3 h-8">产品</th>
                <th className="text-right px-3 h-8">月下载</th>
                {showBaseline && <th className="text-right px-3 h-8">vs AF</th>}
                <th className="text-right px-3 h-8">月收入</th>
                {showBaseline && <th className="text-right px-3 h-8">vs AF</th>}
                <th className="text-right px-3 h-8">排名</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-soft">
              {af && (
                <tr className="bg-pill-blue-bg/40 font-medium">
                  <td className="px-3 h-9">
                    <span className="text-semantic-info">{BASELINE_APP}</span>
                    <span className="ml-2 text-2xs text-pill-blue-fg">[baseline]</span>
                  </td>
                  <td className="px-3 h-9 text-right tabular-nums">
                    {af.downloads_num != null ? formatCompactNumber(af.downloads_num) : "—"}
                  </td>
                  {showBaseline && <td className="px-3 h-9 text-right text-muted-foreground">—</td>}
                  <td className="px-3 h-9 text-right tabular-nums">
                    {af.revenue_num != null ? "$" + formatCompactNumber(af.revenue_num) : "—"}
                  </td>
                  {showBaseline && <td className="px-3 h-9 text-right text-muted-foreground">—</td>}
                  <td className="px-3 h-9 text-right tabular-nums">
                    {af.rank_value != null ? `#${af.rank_value}` : "—"}
                  </td>
                </tr>
              )}
              {others.map((r) => (
                <tr key={r.id} className="hover:bg-muted/30 transition-colors duration-150">
                  <td className="px-3 h-9 font-medium">{r.competitor}</td>
                  <td className="px-3 h-9 text-right tabular-nums">
                    {r.downloads_num != null ? formatCompactNumber(r.downloads_num) : "—"}
                  </td>
                  {showBaseline && (
                    <td className="px-3 h-9 text-right">
                      <BaselineDeltaCell delta={computeNumericDelta(r.downloads_num, af?.downloads_num)} />
                    </td>
                  )}
                  <td className="px-3 h-9 text-right tabular-nums">
                    {r.revenue_num != null ? "$" + formatCompactNumber(r.revenue_num) : "—"}
                  </td>
                  {showBaseline && (
                    <td className="px-3 h-9 text-right">
                      <BaselineDeltaCell delta={computeNumericDelta(r.revenue_num, af?.revenue_num)} />
                    </td>
                  )}
                  <td className="px-3 h-9 text-right tabular-nums">
                    {r.rank_value != null ? `#${r.rank_value}` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
