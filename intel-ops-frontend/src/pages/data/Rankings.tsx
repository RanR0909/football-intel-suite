import { useMemo } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import FilterChips from "@/components/shared/FilterChips"
import RegionChip from "@/components/shared/RegionChip"
import EmptyState from "@/components/shared/EmptyState"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useRank } from "@/hooks/api/useRank"
import { useUrlFilters } from "@/hooks/useUrlFilters"
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

/** delta = ago_rank - rank_value（正数=进步/升、负数=退步/降）
 *  跟 reviews.delta 字段同方向语义。任一为 NULL 时返 null。 */
function rankDelta(rank: number | null, ago: number | null): number | null {
  if (rank == null || ago == null) return null
  return ago - rank
}

const VIEW_OPTIONS = [
  { value: "all",         label: "全部" },
  { value: "new_today",   label: "今日新上榜" },
  { value: "new_this_week", label: "本周新上榜" },
]
type View = "all" | "new_today" | "new_this_week"

const SORT_OPTIONS = [
  { value: "rank",        label: "按当前排名" },
  { value: "daily_up",    label: "日变↑" },
  { value: "daily_down",  label: "日变↓" },
  { value: "weekly_up",   label: "周变↑" },
  { value: "weekly_down", label: "周变↓" },
]
type SortBy = "rank" | "daily_up" | "daily_down" | "weekly_up" | "weekly_down"

/** 两个 ISO 日期串（YYYY-MM-DD）的天数差。a 比 b 早 N 天 → 返回 N。 */
function daysBetween(earlier: string, later: string): number {
  return Math.floor((Date.parse(later) - Date.parse(earlier)) / 86400_000)
}

/** 今日新上榜：first_seen_date == 当前快照的 snapshot_date（即在本源/区域/平台下，
 *  这条记录就是该 app 的首条快照 — 之前从未出现过）。
 *  抓取若间隔几天，"今天"实际是"最新一次抓取的 snapshot_date"。 */
function isNewToday(r: { first_seen_date: string | null; snapshot_date: string }): boolean {
  return !!r.first_seen_date && r.first_seen_date === r.snapshot_date
}

/** 本周新上榜：first_seen_date 距 snapshot_date < 7 天。包含今日新上榜。 */
function isNewThisWeek(r: { first_seen_date: string | null; snapshot_date: string }): boolean {
  if (!r.first_seen_date) return false
  return daysBetween(r.first_seen_date, r.snapshot_date) < 7
}

export default function Rankings() {
  const { value, setValue } = useUrlFilters({
    source: "appmagic", region: "global", competitor: "", sort: "rank", view: "all",
  })

  const source = value("source")
  const region = value("region")
  const competitor = value("competitor")
  const sortBy = (value("sort") || "rank") as SortBy
  const view = (value("view") || "all") as View

  // appstore_rank 只有 US 数据 → 强制 us，UI 不展示国家筛选；
  // appmagic 默认 global（region_code IS NULL 的总榜）
  const effectiveRegion = source === "appstore_rank" ? "us" : (region || "global")

  const { data, isLoading, isError, refetch } = useRank({
    source, region: effectiveRegion, competitor, limit: 200,
  })
  const rows = data?.rankings || []

  // 标准化每行的"展示名"（监控竞品取 competitor，其它取 r.name）
  // + 监控竞品标识（含 AF baseline）+ daily_delta + weekly_delta
  const normalized = useMemo(() => {
    return rows.map((r) => {
      const displayName = r.competitor || r.name || "—"
      const isMonitored = !!r.competitor && MONITORED.has(r.competitor)
      const isBaseline = r.competitor === BASELINE_APP
      return {
        ...r,
        displayName,
        isMonitored,
        isBaseline,
        daily_delta: rankDelta(r.rank_value, r.day_ago_rank),
        weekly_delta: rankDelta(r.rank_value, r.week_ago_rank),
      }
    })
  }, [rows])

  // KPI（去掉"榜单深度"）
  const kpi = useMemo(() => {
    const tracked = new Set(normalized.filter((r) => r.isMonitored).map((r) => r.competitor))
    const monitoredInTop50 = normalized.filter(
      (r) => r.isMonitored && r.rank_value != null && r.rank_value <= 50
    )
    // 今日新上榜 = first_seen_date 就是当前 snapshot_date（这个 app 之前从未在此源/区域/平台出现过）
    const newToday = normalized.filter(
      (r) => r.rank_value != null && isNewToday(r)
    )
    return {
      tracked: tracked.size,
      top50: monitoredInTop50.length,
      newToday: newToday.length,
    }
  }, [normalized])

  // 视图过滤 — view 决定 base 数据集；之后再用 sortBy 排序
  const filtered = useMemo(() => {
    if (view === "new_today") {
      return normalized.filter((r) => r.rank_value != null && isNewToday(r))
    }
    if (view === "new_this_week") {
      return normalized.filter((r) => r.rank_value != null && isNewThisWeek(r))
    }
    return normalized
  }, [normalized, view])

  // 表格行 — AF 第一 + 其他按 sortBy 排
  // 「新上榜」视图下 AF 不置顶（按 rank 升序混排即可，因为这些都是首次进榜）
  const sorted = useMemo(() => {
    const showAfFirst = view === "all"
    const af = showAfFirst ? filtered.find((r) => r.isBaseline) : null
    const others = showAfFirst ? filtered.filter((r) => !r.isBaseline) : filtered

    const cmpDelta = (key: "daily_delta" | "weekly_delta", dir: "up" | "down") =>
      (a: typeof normalized[number], b: typeof normalized[number]) => {
        const da = a[key]
        const db = b[key]
        if (da == null && db == null) return (a.rank_value ?? 9999) - (b.rank_value ?? 9999)
        if (da == null) return 1
        if (db == null) return -1
        return dir === "up" ? db - da : da - db
      }

    if (sortBy === "daily_up")        others.sort(cmpDelta("daily_delta",  "up"))
    else if (sortBy === "daily_down") others.sort(cmpDelta("daily_delta",  "down"))
    else if (sortBy === "weekly_up")  others.sort(cmpDelta("weekly_delta", "up"))
    else if (sortBy === "weekly_down")others.sort(cmpDelta("weekly_delta", "down"))
    else                              others.sort((a, b) => (a.rank_value ?? 9999) - (b.rank_value ?? 9999))

    return { af, others }
  }, [filtered, sortBy, view])

  return (
    <div>
      <PageHeader title="排名异动" />

      <KpiRow>
        <KpiCard label="监控覆盖" value={kpi.tracked} hint={`${kpi.tracked} 个监控竞品上榜`} />
        <KpiCard label="进 Top 50" value={kpi.top50} hint="监控竞品" />
        <KpiCard label="今日新上榜" value={kpi.newToday} hint="昨天未在榜，今天首次进入" />
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
          label="视图"
          options={VIEW_OPTIONS}
          value={view}
          onChange={(v) => setValue("view", v)}
        />
        <FilterChips
          label="排序"
          options={SORT_OPTIONS}
          value={sortBy}
          onChange={(v) => setValue("sort", v)}
        />
        {competitor && (
          <div className="flex items-center justify-between">
            <span className="text-2xs text-muted-foreground">竞品筛选：</span>
            <button
              onClick={() => setValue("competitor", "")}
              className="text-2xs text-muted-foreground hover:text-foreground underline"
            >
              清除 {competitor}
            </button>
          </div>
        )}
      </div>

      {isLoading && <SkeletonTable rows={10} />}
      {isError && <EmptyState type="error" onRetry={() => refetch()} />}
      {!isLoading && !isError && filtered.length === 0 && <EmptyState type="empty" />}

      {filtered.length > 0 && (
        <div className="border border-border-soft rounded-md bg-card overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-muted/30">
              <tr className="text-2xs uppercase tracking-wider text-muted-foreground">
                <th className="text-left px-3 h-8">产品</th>
                <th className="text-left px-3 h-8">国家</th>
                <th className="text-right px-3 h-8">当前排名</th>
                <th
                  className="text-right px-3 h-8 cursor-pointer hover:text-foreground"
                  title="本期 vs 上一次同源 + 同区域 + 同平台 rank 差值（通常是昨天）。点击切换升/降序"
                  onClick={() =>
                    setValue("sort", sortBy === "daily_up" ? "daily_down" : "daily_up")
                  }
                >
                  日变化
                  {sortBy === "daily_up" && <ArrowUp className="inline w-3 h-3 ml-0.5" />}
                  {sortBy === "daily_down" && <ArrowDown className="inline w-3 h-3 ml-0.5" />}
                </th>
                <th
                  className="text-right px-3 h-8 cursor-pointer hover:text-foreground"
                  title="本期 vs 一周前的同源 + 同区域 + 同平台 rank 差值。点击切换升/降序"
                  onClick={() =>
                    setValue("sort", sortBy === "weekly_up" ? "weekly_down" : "weekly_up")
                  }
                >
                  周变化
                  {sortBy === "weekly_up" && <ArrowUp className="inline w-3 h-3 ml-0.5" />}
                  {sortBy === "weekly_down" && <ArrowDown className="inline w-3 h-3 ml-0.5" />}
                </th>
                <th className="text-right px-3 h-8">下载估算</th>
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
                    {renderDelta(sorted.af.daily_delta)}
                  </td>
                  <td className="px-3 h-9 text-right">
                    {renderDelta(sorted.af.weekly_delta)}
                  </td>
                  <td className="px-3 h-9 text-right tabular-nums">
                    {sorted.af.downloads || "—"}
                  </td>
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
                    {renderDelta(r.daily_delta)}
                  </td>
                  <td className="px-3 h-9 text-right">
                    {renderDelta(r.weekly_delta)}
                  </td>
                  <td className="px-3 h-9 text-right tabular-nums">
                    {r.downloads || "—"}
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
