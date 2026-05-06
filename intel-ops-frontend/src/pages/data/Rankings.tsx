import { useMemo, useState } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import FilterChips from "@/components/shared/FilterChips"
import RegionChip from "@/components/shared/RegionChip"
import BaselineToggle from "@/components/shared/BaselineToggle"
import BaselineDeltaCell from "@/components/shared/BaselineDeltaCell"
import EmptyState from "@/components/shared/EmptyState"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useRank } from "@/hooks/api/useRank"
import { useUrlFilters } from "@/hooks/useUrlFilters"
import { computeRankDelta } from "@/lib/baseline"
import { cn } from "@/lib/utils"
import { BASELINE_APP, COMPETITORS, REGION_LABELS, type Region } from "@/types/domain"
import { ArrowUp, ArrowDown, Minus, Star } from "lucide-react"

// 排名异动只展示「全榜」类数据源（Top 100 体育榜）。
// sensor_tower / androidrank 是 per-竞品的财务/历史指标，归属在「收入下载」页面。
const SOURCE_OPTIONS = [
  { value: "appmagic", label: "AppMagic · 总榜 + 12 国" },
  { value: "appstore_rank", label: "App Store · US" },
]

const MONITORED = new Set<string>([...COMPETITORS, BASELINE_APP])

export default function Rankings() {
  const { value, setValue } = useUrlFilters({
    source: "appmagic", region: "global", competitor: "",
  })
  const [showBaseline, setShowBaseline] = useState(true)

  const source = value("source")
  const region = value("region")
  const competitor = value("competitor")

  // appstore_rank 只有 US 数据 → 强制 us，UI 不展示国家筛选；
  // appmagic 默认 global（region_code IS NULL 的总榜）
  const effectiveRegion = source === "appstore_rank" ? "us" : (region || "global")

  const { data, isLoading, isError, refetch } = useRank({
    source, region: effectiveRegion, competitor, limit: 200,
  })
  const rows = data?.rankings || []

  // 标准化每行的"展示名"（监控竞品取 competitor，其它取 r.name）
  // + 是否监控竞品（含 AllFootball baseline）的标识
  const normalized = useMemo(() => {
    return rows.map((r) => {
      const displayName = r.competitor || r.name || "—"
      const isMonitored = !!r.competitor && MONITORED.has(r.competitor)
      const isBaseline = r.competitor === BASELINE_APP
      return { ...r, displayName, isMonitored, isBaseline }
    })
  }, [rows])

  // KPI 计算（基于全榜 + 监控视角）
  const kpi = useMemo(() => {
    const tracked = new Set(normalized.filter((r) => r.isMonitored).map((r) => r.competitor))
    const movers = normalized.filter((r) => r.delta != null && Math.abs(r.delta) >= 5)
    const monitoredInTop50 = normalized.filter(
      (r) => r.isMonitored && r.rank_value != null && r.rank_value <= 50
    )
    return {
      tracked: tracked.size,
      total: normalized.length,
      movers: movers.length,
      top50: monitoredInTop50.length,
    }
  }, [normalized])

  // 表格行 — AF 第一 + 全 Top 榜按 rank 升序
  const sorted = useMemo(() => {
    const af = normalized.find((r) => r.isBaseline)
    const others = normalized
      .filter((r) => !r.isBaseline)
      .sort((a, b) => (a.rank_value ?? 9999) - (b.rank_value ?? 9999))
    return { af, others }
  }, [normalized])
  const afRank = sorted.af?.rank_value ?? null

  return (
    <div>
      <PageHeader
        title="排名异动"
        subtitle={`Top ${rows.length} 体育榜（AllFootball 蓝色 = baseline · ⭐绿底 = 9 监控竞品 · 其它为友商）`}
      />

      <KpiRow>
        <KpiCard label="榜单深度" value={kpi.total} hint="本国 Top 排名总数" />
        <KpiCard label="监控覆盖" value={kpi.tracked} hint={`${kpi.tracked} 个监控竞品上榜`} />
        <KpiCard label="进 Top 50" value={kpi.top50} hint="监控竞品" />
        <KpiCard label="24h 异动 ≥5" value={kpi.movers} hint="rank 变 ≥ 5 名" />
      </KpiRow>

      <div className="space-y-2 mb-3">
        <FilterChips
          label="数据源"
          options={SOURCE_OPTIONS}
          value={source}
          onChange={(v) => setValue("source", v)}
        />
        {source !== "appstore_rank" && (
          <RegionChip
            value={region}
            onChange={(v) => setValue("region", v)}
            showGlobal
          />
        )}
        <div className="flex items-center justify-between">
          <span className="text-2xs text-muted-foreground">竞品筛选：</span>
          <div className="flex items-center gap-3">
            {competitor && (
              <button
                onClick={() => setValue("competitor", "")}
                className="text-2xs text-muted-foreground hover:text-foreground underline"
              >
                清除 {competitor}
              </button>
            )}
            <BaselineToggle show={showBaseline} onChange={setShowBaseline} />
          </div>
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
                <th className="text-left px-3 h-8">国家</th>
                <th className="text-right px-3 h-8">当前排名</th>
                <th className="text-right px-3 h-8">24h 变化</th>
                <th className="text-right px-3 h-8">下载估算</th>
                {showBaseline && (
                  <th className="text-right px-3 h-8">vs AF</th>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-border-soft">
              {sorted.af && (
                <tr className="bg-pill-blue-bg/40 font-medium">
                  <td className="px-3 h-9">
                    <span className="text-semantic-info">{BASELINE_APP}</span>
                    <span className="ml-2 text-2xs text-pill-blue-fg">[baseline]</span>
                  </td>
                  <td className="px-3 h-9">{REGION_LABELS[sorted.af.region_code as Region] || "—"}</td>
                  <td className="px-3 h-9 text-right tabular-nums">
                    {sorted.af.rank_value != null ? `#${sorted.af.rank_value}` : "—"}
                  </td>
                  <td className="px-3 h-9 text-right">
                    {renderDelta(sorted.af.delta)}
                  </td>
                  <td className="px-3 h-9 text-right tabular-nums">
                    {sorted.af.downloads || "—"}
                  </td>
                  {showBaseline && <td className="px-3 h-9 text-right text-muted-foreground">—</td>}
                </tr>
              )}
              {sorted.others.map((r, idx) => (
                <tr
                  key={`${r.id ?? idx}-${r.displayName}`}
                  className={cn(
                    "transition-colors duration-150",
                    r.isMonitored
                      ? "bg-semantic-success/10 hover:bg-semantic-success/15 font-medium"
                      : "hover:bg-muted/30"
                  )}
                >
                  <td className="px-3 h-9">
                    {r.isMonitored && (
                      <Star className="inline w-3 h-3 mr-1 text-semantic-success fill-semantic-success" />
                    )}
                    {r.displayName}
                  </td>
                  <td className="px-3 h-9">{REGION_LABELS[r.region_code as Region] || r.region_code?.toUpperCase() || "—"}</td>
                  <td className="px-3 h-9 text-right tabular-nums">
                    {r.rank_value != null ? `#${r.rank_value}` : "—"}
                  </td>
                  <td className="px-3 h-9 text-right">
                    {renderDelta(r.delta)}
                  </td>
                  <td className="px-3 h-9 text-right tabular-nums">
                    {r.downloads || "—"}
                  </td>
                  {showBaseline && (
                    <td className="px-3 h-9 text-right">
                      {r.isMonitored ? (
                        <BaselineDeltaCell delta={computeRankDelta(r.rank_value, afRank)} />
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
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

function renderDelta(delta: number | null | undefined) {
  if (delta == null) return <span className="text-muted-foreground">—</span>
  if (delta === 0) return <span className="inline-flex items-center text-muted-foreground"><Minus className="w-3 h-3" /></span>
  const up = delta > 0
  return (
    <span className={cn(
      "inline-flex items-center gap-0.5 tabular-nums",
      up ? "text-semantic-success" : "text-semantic-danger"
    )}>
      {up ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />}
      {Math.abs(delta)}
    </span>
  )
}
