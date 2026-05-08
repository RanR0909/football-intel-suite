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

/** 周变化 = week_ago_rank - rank_value（正数=进步/升、负数=退步/降）
 *  跟 reviews.delta 字段同方向语义。week_ago_rank 为 NULL 时返 null。 */
function weeklyDelta(r: { rank_value: number | null; week_ago_rank: number | null }): number | null {
  if (r.rank_value == null || r.week_ago_rank == null) return null
  return r.week_ago_rank - r.rank_value
}

const SORT_OPTIONS = [
  { value: "rank",       label: "按当前排名" },
  { value: "weekly_up",  label: "周变↑（进步多的优先）" },
  { value: "weekly_down", label: "周变↓（退步多的优先）" },
]
type SortBy = "rank" | "weekly_up" | "weekly_down"

export default function Rankings() {
  const { value, setValue } = useUrlFilters({
    source: "appmagic", region: "global", competitor: "", sort: "rank",
  })
  const [showBaseline, setShowBaseline] = useState(true)

  const source = value("source")
  const region = value("region")
  const competitor = value("competitor")
  const sortBy = (value("sort") || "rank") as SortBy

  // appstore_rank 只有 US 数据 → 强制 us，UI 不展示国家筛选；
  // appmagic 默认 global（region_code IS NULL 的总榜）
  const effectiveRegion = source === "appstore_rank" ? "us" : (region || "global")

  const { data, isLoading, isError, refetch } = useRank({
    source, region: effectiveRegion, competitor, limit: 200,
  })
  const rows = data?.rankings || []

  // 标准化每行的"展示名"（监控竞品取 competitor，其它取 r.name）
  // + 是否监控竞品（含 AllFootball baseline）的标识 + weekly_delta
  const normalized = useMemo(() => {
    return rows.map((r) => {
      const displayName = r.competitor || r.name || "—"
      const isMonitored = !!r.competitor && MONITORED.has(r.competitor)
      const isBaseline = r.competitor === BASELINE_APP
      return { ...r, displayName, isMonitored, isBaseline, weekly_delta: weeklyDelta(r) }
    })
  }, [rows])

  // KPI（去掉"榜单深度"；24h 异动 → 周变化 ≥5）
  const kpi = useMemo(() => {
    const tracked = new Set(normalized.filter((r) => r.isMonitored).map((r) => r.competitor))
    const monitoredInTop50 = normalized.filter(
      (r) => r.isMonitored && r.rank_value != null && r.rank_value <= 50
    )
    const weeklyMovers = normalized.filter(
      (r) => r.weekly_delta != null && Math.abs(r.weekly_delta) >= 5
    )
    return {
      tracked: tracked.size,
      top50: monitoredInTop50.length,
      weeklyMovers: weeklyMovers.length,
    }
  }, [normalized])

  // 表格行 — AF 第一 + 其他按 sortBy 排
  const sorted = useMemo(() => {
    const af = normalized.find((r) => r.isBaseline)
    const others = normalized.filter((r) => !r.isBaseline)
    if (sortBy === "weekly_up") {
      // 周变↑：weekly_delta 大的优先；NULL 排到最后
      others.sort((a, b) => {
        const da = a.weekly_delta
        const db = b.weekly_delta
        if (da == null && db == null) return (a.rank_value ?? 9999) - (b.rank_value ?? 9999)
        if (da == null) return 1
        if (db == null) return -1
        return db - da
      })
    } else if (sortBy === "weekly_down") {
      // 周变↓：weekly_delta 小（负多）的优先；NULL 排到最后
      others.sort((a, b) => {
        const da = a.weekly_delta
        const db = b.weekly_delta
        if (da == null && db == null) return (a.rank_value ?? 9999) - (b.rank_value ?? 9999)
        if (da == null) return 1
        if (db == null) return -1
        return da - db
      })
    } else {
      // 默认 — 按当前排名升序
      others.sort((a, b) => (a.rank_value ?? 9999) - (b.rank_value ?? 9999))
    }
    return { af, others }
  }, [normalized, sortBy])
  const afRank = sorted.af?.rank_value ?? null

  return (
    <div>
      <PageHeader title="排名异动" />

      <KpiRow>
        <KpiCard label="监控覆盖" value={kpi.tracked} hint={`${kpi.tracked} 个监控竞品上榜`} />
        <KpiCard label="进 Top 50" value={kpi.top50} hint="监控竞品" />
        <KpiCard label="一周异动 ≥5" value={kpi.weeklyMovers} hint="周排名变 ≥ 5 名" />
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
        <FilterChips
          label="排序"
          options={SORT_OPTIONS}
          value={sortBy}
          onChange={(v) => setValue("sort", v)}
        />
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
                <th className="text-right px-3 h-8" title="本期 vs 一周前的同源 + 同区域 + 同平台 rank 差值">周变化</th>
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
                    {renderDelta(sorted.af.weekly_delta)}
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
                    {renderDelta(r.weekly_delta)}
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
