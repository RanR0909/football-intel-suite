/** 广告投放页（spec 前端实现文档 §9.11）
 *
 * 改造点 vs v1:
 *  · 主视图改 3 tab：卖点策略 / 区域策略 / 竞品创意对比
 *  · 数据 = /api/ads/aggregated（task #7 ad_selling_point 输出聚合）
 *  · 底部保留按竞品列文案作下钻
 */
import { useMemo } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import FilterChips from "@/components/shared/FilterChips"
import AppScopeChip from "@/components/shared/AppScopeChip"
import EmptyState from "@/components/shared/EmptyState"
import Pill from "@/components/shared/Pill"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useAds } from "@/hooks/api/useAds"
import { useAdsAggregated } from "@/hooks/api/useAggregated"
import { useUrlFilters } from "@/hooks/useUrlFilters"
import { useFilterStore } from "@/stores/filterStore"
import {
  BASELINE_APP, COMPETITORS, REGION_LABELS,
  SELLING_POINT_LABELS, AUDIENCE_LABELS, TONE_LABELS,
  type Region,
} from "@/types/domain"
import type {
  AdsAggSellingRow, AdsAggRegionRow, AdsAggCompetitorRow,
} from "@/types/api"

const TABS = [
  { value: "selling_point", label: "卖点策略" },
  { value: "region",        label: "区域策略" },
  { value: "competitor",    label: "竞品创意对比" },
] as const
type Tab = typeof TABS[number]["value"]

const COUNTRY_OPTIONS = [
  { value: "", label: "全部" },
  { value: "us", label: REGION_LABELS.us },
  { value: "gb", label: REGION_LABELS.gb },
  { value: "br", label: REGION_LABELS.br },
  { value: "ng", label: REGION_LABELS.ng },
  { value: "jp", label: REGION_LABELS.jp },
]

export default function Ads() {
  const { value, setValue } = useUrlFilters({
    tab: "selling_point", country: "", competitor: "",
  })
  const tab = (value("tab") || "selling_point") as Tab
  const country = value("country")
  const competitor = value("competitor")
  const { appScope } = useFilterStore()

  // 拉总览（用于 KPI + 底部下钻）
  const { data: rawAds } = useAds({ country, competitor, limit: 500 })
  const filteredAds = useMemo(() => {
    return (rawAds?.ads || []).filter((a) => {
      if (appScope === "competitor" && a.competitor === BASELINE_APP) return false
      if (appScope === "baseline" && a.competitor !== BASELINE_APP) return false
      return true
    })
  }, [rawAds, appScope])

  const kpi = useMemo(() => {
    const total = filteredAds.length
    const recentCount = filteredAds.filter((a) => {
      if (!a.start_date) return false
      const d = new Date(a.start_date)
      return Number.isFinite(d.valueOf()) && (Date.now() - d.valueOf()) / 86400_000 <= 7
    }).length
    // 主推卖点
    const spTally: Record<string, number> = {}
    for (const a of filteredAds) for (const sp of a.selling_points || []) spTally[sp] = (spTally[sp] || 0) + 1
    const topSp = Object.entries(spTally).sort((a, b) => b[1] - a[1])[0]
    // 主投国家
    const cTally: Record<string, number> = {}
    for (const a of filteredAds) cTally[a.region] = (cTally[a.region] || 0) + 1
    const topC = Object.entries(cTally).sort((a, b) => b[1] - a[1])[0]
    return {
      total,
      recent: recentCount,
      topSp: topSp ? `${SELLING_POINT_LABELS[topSp[0] as keyof typeof SELLING_POINT_LABELS] || topSp[0]} (${topSp[1]})` : "—",
      topC:  topC  ? `${REGION_LABELS[topC[0] as Region] || topC[0].toUpperCase()} (${topC[1]})` : "—",
    }
  }, [filteredAds])

  // 已分类 vs 未分类
  const classifiedRatio = useMemo(() => {
    const tot = filteredAds.length
    const c = filteredAds.filter((a) => a.selling_classified_at).length
    return { tot, c }
  }, [filteredAds])

  return (
    <div>
      <PageHeader
        title="广告投放"
        subtitle="Meta 广告库 · 按卖点 / 区域 / 竞品三维度分析"
        right={
          <span className="text-xs text-muted-foreground tabular-nums">
            AI 已分类 {classifiedRatio.c}/{classifiedRatio.tot}
          </span>
        }
      />

      <KpiRow>
        <KpiCard label="活跃创意" value={kpi.total} hint="所有 region" />
        <KpiCard label="近 7d 新增" value={kpi.recent} />
        <KpiCard label="主推卖点" value={kpi.topSp} />
        <KpiCard label="主投国家" value={kpi.topC} />
      </KpiRow>

      <div className="space-y-2 mb-3">
        <AppScopeChip />
        <FilterChips
          label="维度"
          options={TABS.map((t) => ({ value: t.value, label: t.label }))}
          value={tab}
          onChange={(v) => setValue("tab", v)}
        />
        <FilterChips label="国家" options={COUNTRY_OPTIONS} value={country}
                     onChange={(v) => setValue("country", v)} />
        <FilterChips
          label="竞品"
          options={[
            { value: "", label: "全部" },
            ...COMPETITORS.map((c) => ({ value: c, label: c })),
            { value: BASELINE_APP, label: BASELINE_APP },
          ]}
          value={competitor}
          onChange={(v) => setValue("competitor", v)}
        />
      </div>

      {tab === "selling_point" && <TabSellingPoint />}
      {tab === "region"        && <TabRegion />}
      {tab === "competitor"    && <TabCompetitor />}

      {/* 底部下钻：原始创意流（保留） */}
      <details className="mt-4">
        <summary className="text-2xs uppercase tracking-wider text-muted-foreground cursor-pointer mb-2">
          按竞品列原文（{filteredAds.length} 条）
        </summary>
        {filteredAds.length === 0 ? (
          <EmptyState type="empty" />
        ) : (
          <div className="space-y-1">
            {filteredAds.slice(0, 100).map((a) => (
              <div key={a.id} className="text-xs flex items-baseline gap-2 px-2 py-1 border-b border-border-soft">
                <span className="font-medium">{a.competitor}</span>
                <Pill variant="gray">{a.region.toUpperCase()}</Pill>
                {(a.selling_points || []).slice(0, 2).map((sp) => (
                  <Pill key={sp} variant="amber">{SELLING_POINT_LABELS[sp]}</Pill>
                ))}
                <span className="text-muted-foreground line-clamp-1 flex-1">{a.body_text || "(无文案)"}</span>
              </div>
            ))}
          </div>
        )}
      </details>
    </div>
  )
}

// ─────────── Tab 1 · 卖点策略 ───────────

function TabSellingPoint() {
  const { data, isLoading, isError, refetch } = useAdsAggregated("selling_point", 30)
  if (isLoading) return <SkeletonTable rows={5} />
  if (isError) return <EmptyState type="error" onRetry={() => refetch()} />
  const items = (data?.items || []) as AdsAggSellingRow[]
  if (!items.length) return <EmptyState type="empty" hint="task #7 ad_selling_point 还没分类任何创意" />

  return (
    <div className="border border-border-soft rounded-md bg-card overflow-hidden">
      <table className="w-full text-xs">
        <thead className="bg-muted/30">
          <tr className="text-2xs uppercase tracking-wider text-muted-foreground">
            <th className="text-left px-3 h-8">卖点</th>
            <th className="text-right px-3 h-8 tabular-nums">创意数</th>
            <th className="text-right px-3 h-8 tabular-nums">竞品数</th>
            <th className="text-left px-3 h-8">主推竞品 Top 3</th>
          </tr>
        </thead>
        <tbody>
          {items.map((row) => (
            <tr key={row.selling_point} className="border-t border-border-soft hover:bg-muted/30">
              <td className="px-3 py-2">
                <Pill variant="amber">{SELLING_POINT_LABELS[row.selling_point]}</Pill>
                <span className="ml-1 font-mono text-2xs text-muted-foreground">{row.selling_point}</span>
              </td>
              <td className="text-right px-3 py-2 tabular-nums font-mono">{row.creative_count}</td>
              <td className="text-right px-3 py-2 tabular-nums font-mono">{row.comp_count}</td>
              <td className="px-3 py-2">
                <div className="flex flex-wrap gap-1">
                  {(row.top_competitors || []).map((tc) => (
                    <Pill key={tc.competitor} variant="blue">{tc.competitor} {tc.n}</Pill>
                  ))}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─────────── Tab 2 · 区域策略 ───────────

function TabRegion() {
  const { data, isLoading, isError, refetch } = useAdsAggregated("region", 30)
  if (isLoading) return <SkeletonTable rows={5} />
  if (isError) return <EmptyState type="error" onRetry={() => refetch()} />
  const items = (data?.items || []) as AdsAggRegionRow[]
  if (!items.length) return <EmptyState type="empty" />

  return (
    <div className="border border-border-soft rounded-md bg-card overflow-hidden">
      <table className="w-full text-xs">
        <thead className="bg-muted/30">
          <tr className="text-2xs uppercase tracking-wider text-muted-foreground">
            <th className="text-left  px-3 h-8">区域</th>
            <th className="text-right px-3 h-8 tabular-nums">总投放数</th>
            <th className="text-right px-3 h-8 tabular-nums">竞品数</th>
          </tr>
        </thead>
        <tbody>
          {items.map((row) => (
            <tr key={row.region} className="border-t border-border-soft hover:bg-muted/30">
              <td className="px-3 py-2 font-mono">
                {REGION_LABELS[row.region as Region] || row.region.toUpperCase()}
              </td>
              <td className="text-right px-3 py-2 tabular-nums font-mono">{row.creative_count}</td>
              <td className="text-right px-3 py-2 tabular-nums font-mono">{row.comp_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─────────── Tab 3 · 竞品创意对比 ───────────

function TabCompetitor() {
  const { data, isLoading, isError, refetch } = useAdsAggregated("competitor", 30)
  if (isLoading) return <SkeletonTable rows={5} />
  if (isError) return <EmptyState type="error" onRetry={() => refetch()} />
  const items = (data?.items || []) as AdsAggCompetitorRow[]
  if (!items.length) return <EmptyState type="empty" />

  return (
    <div className="space-y-2">
      {items.map((row) => {
        const total = row.creative_count
        return (
          <article key={row.competitor} className="border border-border-soft rounded-md bg-card p-3">
            <div className="flex items-baseline gap-2 mb-2">
              <span className="text-sm font-medium">{row.competitor}</span>
              <span className="text-2xs text-muted-foreground tabular-nums ml-auto">
                {row.creative_count} 创意
              </span>
            </div>
            {/* 卖点构成（百分比堆叠） */}
            <div className="flex h-6 w-full overflow-hidden rounded text-2xs">
              {(row.selling_points_breakdown || []).map((sp, i) => {
                const pct = total > 0 ? (sp.n / total * 100) : 0
                return (
                  <div
                    key={sp.selling_point}
                    className={"flex items-center justify-center font-mono text-foreground/80 " +
                      ["bg-pill-amber-bg","bg-pill-teal-bg","bg-pill-blue-bg","bg-pill-purple-bg",
                       "bg-pill-pink-bg","bg-pill-green-bg","bg-pill-red-bg","bg-pill-gray-bg"][i % 8]}
                    style={{ width: `${pct}%` }}
                    title={`${SELLING_POINT_LABELS[sp.selling_point]} · ${sp.n} (${pct.toFixed(0)}%)`}
                  >
                    {pct >= 8 && `${pct.toFixed(0)}%`}
                  </div>
                )
              })}
            </div>
            {/* 卖点 legend */}
            <div className="mt-2 flex flex-wrap gap-1">
              {(row.selling_points_breakdown || []).map((sp) => (
                <Pill key={sp.selling_point} variant="gray">
                  {SELLING_POINT_LABELS[sp.selling_point]} · {sp.n}
                </Pill>
              ))}
            </div>
          </article>
        )
      })}
    </div>
  )
}

// 未使用但保留 — 用于未来可能的 audience/tone 展示
void AUDIENCE_LABELS
void TONE_LABELS
