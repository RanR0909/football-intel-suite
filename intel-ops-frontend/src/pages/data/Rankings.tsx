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
import { BASELINE_APP, REGION_LABELS, type Region } from "@/types/domain"
import { ArrowUp, ArrowDown, Minus } from "lucide-react"

const SOURCE_OPTIONS = [
  { value: "appstore_rank", label: "App Store" },
  { value: "appmagic", label: "AppMagic" },
  { value: "sensor_tower", label: "Sensor Tower" },
  { value: "androidrank", label: "Androidrank" },
]

export default function Rankings() {
  const { value, setValue } = useUrlFilters({
    source: "appstore_rank", region: "us", competitor: "",
  })
  const [showBaseline, setShowBaseline] = useState(true)

  const source = value("source")
  const region = value("region")
  const competitor = value("competitor")

  const { data, isLoading, isError, refetch } = useRank({
    source, region, competitor, limit: 200,
  })
  const rows = data?.rankings || []

  // KPI 计算
  const kpi = useMemo(() => {
    const tracked = new Set(rows.filter((r) => r.competitor).map((r) => r.competitor))
    const movers = rows.filter((r) => r.delta != null && Math.abs(r.delta) >= 5)
    const top50 = rows.filter((r) => r.rank_value != null && r.rank_value <= 50 && r.competitor)
    return {
      tracked: tracked.size,
      movers: movers.length,
      top50: top50.length,
      sources: new Set(rows.map((r) => r.source)).size,
    }
  }, [rows])

  // 表格行 — AF 第一行 + 竞品按 rank 升序
  const sorted = useMemo(() => {
    const af = rows.find((r) => r.competitor === BASELINE_APP)
    const others = rows
      .filter((r) => r.competitor && r.competitor !== BASELINE_APP)
      .sort((a, b) => (a.rank_value ?? 999) - (b.rank_value ?? 999))
    return { af, others }
  }, [rows])
  const afRank = sorted.af?.rank_value ?? null

  return (
    <div>
      <PageHeader
        title="排名异动"
        subtitle={`${rows.length} 条快照（最近 7 天，AllFootball 蓝色行 = baseline）`}
      />

      <KpiRow>
        <KpiCard label="追踪 app 数" value={kpi.tracked} />
        <KpiCard label="24h 异动 ≥5" value={kpi.movers} hint="rank 变 ≥ 5 名" />
        <KpiCard label="进 Top 50" value={kpi.top50} />
        <KpiCard label="数据源" value={kpi.sources} hint={SOURCE_OPTIONS.find(s => s.value === source)?.label || "—"} />
      </KpiRow>

      <div className="space-y-2 mb-3">
        <FilterChips
          label="数据源"
          options={SOURCE_OPTIONS}
          value={source}
          onChange={(v) => setValue("source", v)}
        />
        <RegionChip value={region} onChange={(v) => setValue("region", v)} />
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
              {sorted.others.map((r) => (
                <tr key={r.id} className="hover:bg-muted/30 transition-colors duration-150">
                  <td className="px-3 h-9 font-medium">{r.competitor}</td>
                  <td className="px-3 h-9">{REGION_LABELS[r.region_code as Region] || r.region_code?.toUpperCase()}</td>
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
                      <BaselineDeltaCell delta={computeRankDelta(r.rank_value, afRank)} />
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
