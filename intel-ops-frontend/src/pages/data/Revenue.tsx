/** 收入下载页
 *
 * 数据现实（按 source 字段覆盖）：
 *   sensor_tower → us 1 国，dl + rev + rank 全有  (10 条 / 10 竞品)
 *   androidrank  → 不分国家，仅 Android dl       (8 条 / 8 竞品，rev 永远 0)
 *   appmagic     → 12 国，仅排名（dl/rev 全 NULL） → 不在本页列出，去"排名异动"
 *
 * 所以本页：
 *   · source chip 只列 sensor_tower / androidrank
 *   · sensor_tower 选中 → region 锁 us
 *   · androidrank 选中 → region 隐藏（数据本身不分国家），revenue 列也隐藏
 */
import { useMemo, useState } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import FilterChips from "@/components/shared/FilterChips"
import BaselineToggle from "@/components/shared/BaselineToggle"
import BaselineDeltaCell from "@/components/shared/BaselineDeltaCell"
import EmptyState from "@/components/shared/EmptyState"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useRank } from "@/hooks/api/useRank"
import { useUrlFilters } from "@/hooks/useUrlFilters"
import { computeNumericDelta } from "@/lib/baseline"
import { formatCompactNumber } from "@/lib/utils"
import { BASELINE_APP } from "@/types/domain"

type Source = "sensor_tower" | "androidrank"

interface SourceMeta {
  value: Source
  label: string
  /** 该源原生支持哪些区域。空数组 = 不分国家（全球总） */
  regions: string[]
  hasRevenue: boolean
  hasRank: boolean
  hint: string
}

const SOURCES: SourceMeta[] = [
  {
    value: "sensor_tower",
    label: "Sensor Tower",
    regions: ["us"],
    hasRevenue: true,
    hasRank: true,
    hint: "仅美区 · 月估算 · 下载+收入+排名",
  },
  {
    value: "androidrank",
    label: "Androidrank",
    regions: [],
    hasRevenue: false,
    hasRank: false,
    hint: "全球总 · 仅 Android · 仅下载（无收入数据）",
  },
]

export default function Revenue() {
  const { value, setValue } = useUrlFilters({
    source: "sensor_tower", region: "us",
  })
  const [showBaseline, setShowBaseline] = useState(true)
  const source = value("source") as Source
  const meta = SOURCES.find((s) => s.value === source) || SOURCES[0]

  // sensor_tower → 锁 us；androidrank → region 字段对它无意义，传空
  const region = meta.regions.length > 0 ? meta.regions[0] : ""
  // 选中 source 时若 URL 上 region 不在该 source 支持列表，自动 reset
  if (value("region") !== region) {
    // 静默修正 URL（避免下次刷新还是错的）
    setTimeout(() => setValue("region", region), 0)
  }

  const { data, isLoading, isError, refetch } = useRank({
    source, region: region || undefined, limit: 100,
  })
  const rows = data?.rankings || []

  const af = rows.find((r) => r.competitor === BASELINE_APP)
  const others = useMemo(
    () => rows.filter((r) => r.competitor && r.competitor !== BASELINE_APP)
      .sort((a, b) => {
        if (meta.hasRevenue) return (b.revenue_num || 0) - (a.revenue_num || 0)
        return (b.downloads_num || 0) - (a.downloads_num || 0)
      }),
    [rows, meta.hasRevenue]
  )

  return (
    <div>
      <PageHeader
        title="收入下载"
        subtitle={`以 AF 为基准对比 9 监控竞品 · ${meta.label}（${meta.hint}）`}
      />

      <KpiRow>
        <KpiCard
          label="AF 月下载"
          value={af?.downloads_num != null ? formatCompactNumber(af.downloads_num) : "—"}
          hint={region ? `${region.toUpperCase()} 区` : "全球"}
        />
        {meta.hasRevenue ? (
          <KpiCard
            label="AF 月收入"
            value={af?.revenue_num != null ? "$" + formatCompactNumber(af.revenue_num) : "—"}
            hint={region ? `${region.toUpperCase()} 区` : "全球"}
          />
        ) : (
          <KpiCard label="AF 月收入" value="—" hint={`${meta.label} 不提供`} />
        )}
        <KpiCard
          label="AF 排名"
          value={af?.rank_value != null && meta.hasRank ? `#${af.rank_value}` : "—"}
          hint={meta.hasRank ? "体育榜" : `${meta.label} 不提供`}
        />
        <KpiCard
          label="数据完整度"
          value={`${
            others.filter((r) => meta.hasRevenue ? r.revenue_num != null : r.downloads_num != null).length
          }/${others.length}`}
          hint={`竞品有${meta.hasRevenue ? "收入" : "下载"}数据的`}
        />
      </KpiRow>

      <div className="space-y-2 mb-3">
        <FilterChips
          label="数据源"
          options={SOURCES.map((s) => ({ value: s.value, label: s.label }))}
          value={source}
          onChange={(v) => setValue("source", v)}
        />
        {/* 区域 chip 只在 source 有多区域时展示；否则一行说明实际覆盖 */}
        {meta.regions.length > 1 ? (
          <FilterChips
            label="区域"
            options={meta.regions.map((r) => ({ value: r, label: r.toUpperCase() }))}
            value={region}
            onChange={(v) => setValue("region", v)}
          />
        ) : (
          <div className="text-2xs text-muted-foreground pl-1">
            <span className="font-mono">{meta.label}</span>:
            {meta.regions.length === 1
              ? <> 数据仅覆盖 <span className="font-mono font-medium">{meta.regions[0].toUpperCase()}</span> 区域</>
              : <> 数据不分国家（全球总）</>
            }
          </div>
        )}
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
                {meta.hasRevenue && <th className="text-right px-3 h-8">月收入</th>}
                {meta.hasRevenue && showBaseline && <th className="text-right px-3 h-8">vs AF</th>}
                {meta.hasRank && <th className="text-right px-3 h-8">排名</th>}
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
                  {meta.hasRevenue && (
                    <td className="px-3 h-9 text-right tabular-nums">
                      {af.revenue_num != null ? "$" + formatCompactNumber(af.revenue_num) : "—"}
                    </td>
                  )}
                  {meta.hasRevenue && showBaseline && (
                    <td className="px-3 h-9 text-right text-muted-foreground">—</td>
                  )}
                  {meta.hasRank && (
                    <td className="px-3 h-9 text-right tabular-nums">
                      {af.rank_value != null ? `#${af.rank_value}` : "—"}
                    </td>
                  )}
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
                  {meta.hasRevenue && (
                    <td className="px-3 h-9 text-right tabular-nums">
                      {r.revenue_num != null ? "$" + formatCompactNumber(r.revenue_num) : "—"}
                    </td>
                  )}
                  {meta.hasRevenue && showBaseline && (
                    <td className="px-3 h-9 text-right">
                      <BaselineDeltaCell delta={computeNumericDelta(r.revenue_num, af?.revenue_num)} />
                    </td>
                  )}
                  {meta.hasRank && (
                    <td className="px-3 h-9 text-right tabular-nums">
                      {r.rank_value != null ? `#${r.rank_value}` : "—"}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
