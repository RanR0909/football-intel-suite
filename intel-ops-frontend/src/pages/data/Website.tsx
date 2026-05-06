import { useMemo, useState } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import BaselineToggle from "@/components/shared/BaselineToggle"
import BaselineDeltaCell from "@/components/shared/BaselineDeltaCell"
import EmptyState from "@/components/shared/EmptyState"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useWebsite } from "@/hooks/api/useWebsite"
import { computeNumericDelta, computeRankDelta } from "@/lib/baseline"
import { formatPct, formatCompactNumber } from "@/lib/utils"
import { BASELINE_APP } from "@/types/domain"

export default function Website() {
  const [showBaseline, setShowBaseline] = useState(true)
  const { data, isLoading, isError, refetch } = useWebsite({})
  const rows = data?.website || []
  const af = rows.find((r) => r.competitor === BASELINE_APP)
  const others = useMemo(
    () => rows.filter((r) => r.competitor !== BASELINE_APP)
      .sort((a, b) => (b.monthly_visits_num || 0) - (a.monthly_visits_num || 0)),
    [rows]
  )

  return (
    <div>
      <PageHeader
        title="网站数据"
        subtitle="Similarweb 公开页 · trial-only 字段已永久删除（device / 6 渠道分布 / top_keywords）"
      />

      <KpiRow>
        <KpiCard
          label="AF 月访问"
          value={af ? af.monthly_visits || formatCompactNumber(af.monthly_visits_num) : "—"}
          hint="本月"
        />
        <KpiCard
          label="AF 平均停留"
          value={af?.avg_visit_duration || "—"}
        />
        <KpiCard
          label="AF 跳出率"
          value={formatPct(af?.bounce_rate)}
        />
        <KpiCard
          label="AF 全球排名"
          value={af?.global_rank ? `#${af.global_rank.toLocaleString()}` : "—"}
          hint={af?.country_rank_country ? `主要国家 ${af.country_rank_country}` : ""}
        />
      </KpiRow>

      <div className="flex justify-end mb-3">
        <BaselineToggle show={showBaseline} onChange={setShowBaseline} />
      </div>

      {isLoading && <SkeletonTable rows={6} />}
      {isError && <EmptyState type="error" onRetry={() => refetch()} />}
      {!isLoading && !isError && rows.length === 0 && <EmptyState type="empty" />}

      {rows.length > 0 && (
        <div className="border border-border-soft rounded-md bg-card overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-muted/30 text-2xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left px-3 h-8">产品</th>
                <th className="text-right px-3 h-8">月访问</th>
                {showBaseline && <th className="text-right px-3 h-8">vs AF</th>}
                <th className="text-right px-3 h-8">平均停留</th>
                <th className="text-right px-3 h-8">页/访问</th>
                <th className="text-right px-3 h-8">跳出率</th>
                <th className="text-right px-3 h-8">全球排名</th>
                {showBaseline && <th className="text-right px-3 h-8">vs AF</th>}
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
                    {af.monthly_visits || formatCompactNumber(af.monthly_visits_num)}
                  </td>
                  {showBaseline && <td className="px-3 h-9 text-right text-muted-foreground">—</td>}
                  <td className="px-3 h-9 text-right tabular-nums">{af.avg_visit_duration || "—"}</td>
                  <td className="px-3 h-9 text-right tabular-nums">{af.pages_per_visit?.toFixed(2) || "—"}</td>
                  <td className="px-3 h-9 text-right tabular-nums">{formatPct(af.bounce_rate)}</td>
                  <td className="px-3 h-9 text-right tabular-nums">
                    {af.global_rank ? `#${af.global_rank.toLocaleString()}` : "—"}
                  </td>
                  {showBaseline && <td className="px-3 h-9 text-right text-muted-foreground">—</td>}
                </tr>
              )}
              {others.map((r) => (
                <tr key={r.id} className="hover:bg-muted/30 transition-colors duration-150">
                  <td className="px-3 h-9 font-medium">{r.competitor}</td>
                  <td className="px-3 h-9 text-right tabular-nums">
                    {r.monthly_visits || formatCompactNumber(r.monthly_visits_num)}
                  </td>
                  {showBaseline && (
                    <td className="px-3 h-9 text-right">
                      <BaselineDeltaCell delta={computeNumericDelta(r.monthly_visits_num, af?.monthly_visits_num)} />
                    </td>
                  )}
                  <td className="px-3 h-9 text-right tabular-nums">{r.avg_visit_duration || "—"}</td>
                  <td className="px-3 h-9 text-right tabular-nums">{r.pages_per_visit?.toFixed(2) || "—"}</td>
                  <td className="px-3 h-9 text-right tabular-nums">{formatPct(r.bounce_rate)}</td>
                  <td className="px-3 h-9 text-right tabular-nums">
                    {r.global_rank ? `#${r.global_rank.toLocaleString()}` : "—"}
                  </td>
                  {showBaseline && (
                    <td className="px-3 h-9 text-right">
                      <BaselineDeltaCell delta={computeRankDelta(r.global_rank, af?.global_rank)} />
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 长尾：Top Countries（Similar Sites 已删除 — 实际用处不大） */}
      {rows.length > 0 && (
        <section className="mt-4 border border-border-soft rounded-md bg-card overflow-hidden">
          <header className="px-3 h-8 bg-muted/30 border-b border-border-soft flex items-center">
            <span className="text-sm font-medium">Top Countries</span>
          </header>
          <div className="p-3 text-xs space-y-2">
            {rows.filter((r) => r.top_countries?.length).map((r) => (
              <div key={r.id}>
                <div className="font-medium mb-1">{r.competitor}</div>
                <div className="flex flex-wrap gap-1">
                  {r.top_countries.slice(0, 5).map((c, i) => (
                    <span key={i} className="px-1.5 h-5 inline-flex items-center gap-1 rounded bg-muted/40 text-2xs">
                      <span>{c.country}</span>
                      <span className="tabular-nums text-muted-foreground">{formatPct(c.share)}</span>
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
