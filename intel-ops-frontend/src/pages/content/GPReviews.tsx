import { useMemo } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import FilterChips from "@/components/shared/FilterChips"
import AppScopeChip from "@/components/shared/AppScopeChip"
import RegionChip from "@/components/shared/RegionChip"
import EmptyState from "@/components/shared/EmptyState"
import Pill from "@/components/shared/Pill"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useReviews } from "@/hooks/api/useReviews"
import { useUrlFilters } from "@/hooks/useUrlFilters"
import { useFilterStore } from "@/stores/filterStore"
import { cn } from "@/lib/utils"
import { BASELINE_APP, COMPETITORS, REVIEW_LABEL_DISPLAY, ENTITY_TYPE_DISPLAY } from "@/types/domain"
import type { ReviewLabel, EntityType } from "@/types/api"

const LABEL_KEYS: ReviewLabel[] = [
  "complaint", "feature_request", "competitor_compare",
  "churn_signal", "positive", "other",
]

export default function GPReviews() {
  const { value, setValue } = useUrlFilters({
    competitor: "", label: "", region: "", since: "7d",
  })
  const competitor = value("competitor")
  const label = value("label")
  const region = value("region")
  const since = value("since")
  const { appScope } = useFilterStore()

  const { data, isLoading, isError, refetch } = useReviews({
    competitor, label, region, since, limit: 500,
  })
  const all = data?.reviews || []
  const filtered = useMemo(() => {
    return all.filter((r) => {
      if (appScope === "competitor" && r.competitor === BASELINE_APP) return false
      if (appScope === "baseline" && r.competitor !== BASELINE_APP) return false
      return true
    })
  }, [all, appScope])

  // 6 类标签矩阵：9 行 × 6 列
  const matrix = useMemo(() => {
    const apps = COMPETITORS as readonly string[]
    const m: Record<string, Record<ReviewLabel, number>> = {}
    for (const app of apps) {
      m[app] = { complaint: 0, feature_request: 0, competitor_compare: 0,
                 churn_signal: 0, positive: 0, other: 0 }
    }
    for (const r of filtered) {
      if (r.label && m[r.competitor]) {
        m[r.competitor][r.label as ReviewLabel] += 1
      }
    }
    return m
  }, [filtered])

  const kpi = useMemo(() => ({
    total: filtered.length,
    request: filtered.filter((r) => r.label === "feature_request").length,
    complaint: filtered.filter((r) => r.label === "complaint").length,
    churn: filtered.filter((r) => r.label === "churn_signal").length,
  }), [filtered])

  return (
    <div>
      <PageHeader title="GP 评论" subtitle="6 类标签矩阵 + 评论原文 + 实体抽取" />

      <KpiRow>
        <KpiCard label="总评论数" value={kpi.total} hint={`已 AI 标 · ${since}`} />
        <KpiCard label="高价值请求" value={kpi.request} />
        <KpiCard label="问题抱怨" value={kpi.complaint} />
        <KpiCard label="流失信号" value={kpi.churn} />
      </KpiRow>

      <div className="space-y-2 mb-3">
        <AppScopeChip />
        <FilterChips
          label="时间"
          options={[
            { value: "24h", label: "24h" },
            { value: "3d", label: "3d" },
            { value: "7d", label: "7d" },
            { value: "30d", label: "30d" },
          ]}
          value={since}
          onChange={(v) => setValue("since", v)}
        />
        <FilterChips
          label="标签"
          options={[
            { value: "", label: "全部" },
            ...LABEL_KEYS.map((k) => ({
              value: k,
              label: REVIEW_LABEL_DISPLAY[k].text,
              badge: filtered.filter((r) => r.label === k).length,
            })),
          ]}
          value={label}
          onChange={(v) => setValue("label", v)}
        />
        <RegionChip value={region} onChange={(v) => setValue("region", v)} />
      </div>

      {/* 6 类标签矩阵 */}
      {!competitor && !label && (
        <div className="border border-border-soft rounded-md bg-card overflow-hidden mb-4">
          <header className="px-3 h-9 bg-muted/30 border-b border-border-soft flex items-center">
            <span className="text-sm font-medium">6 类标签矩阵</span>
            <span className="ml-2 text-2xs text-muted-foreground">点单元格下钻</span>
          </header>
          <table className="w-full text-xs">
            <thead className="text-2xs text-muted-foreground">
              <tr>
                <th className="text-left px-3 py-1.5">竞品</th>
                {LABEL_KEYS.map((k) => (
                  <th key={k} className="text-right px-3 py-1.5">
                    {REVIEW_LABEL_DISPLAY[k].text}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border-soft">
              {COMPETITORS.map((app) => (
                <tr key={app} className="hover:bg-muted/30">
                  <td className="px-3 py-1.5 font-medium">{app}</td>
                  {LABEL_KEYS.map((k) => {
                    const n = matrix[app]?.[k] ?? 0
                    return (
                      <td key={k} className="text-right px-3 py-1.5">
                        <button
                          onClick={() => {
                            setValue("competitor", app)
                            setValue("label", k)
                          }}
                          disabled={n === 0}
                          className={cn(
                            "tabular-nums px-1.5 h-5 rounded inline-flex items-center justify-center min-w-8",
                            n > 0 ? "hover:bg-foreground hover:text-background cursor-pointer" : "text-muted-foreground/40"
                          )}
                        >
                          {n}
                        </button>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 下钻评论流 */}
      {(competitor || label) && (
        <div className="border border-border-soft rounded-md bg-card overflow-hidden">
          <header className="px-3 h-9 bg-muted/30 border-b border-border-soft flex items-center justify-between">
            <span className="text-sm font-medium">
              {competitor || "全部"}
              {label && (
                <>
                  <span className="text-muted-foreground"> · </span>
                  <Pill variant={REVIEW_LABEL_DISPLAY[label as ReviewLabel]?.color.replace("pill-", "") as "purple" | "teal" | "amber" | "blue" | "pink" | "red" | "green" | "gray"}>
                    {REVIEW_LABEL_DISPLAY[label as ReviewLabel]?.text}
                  </Pill>
                </>
              )}
            </span>
            <span className="text-2xs text-muted-foreground">{filtered.length} 条</span>
          </header>

          {isLoading && <SkeletonTable rows={6} />}
          {isError && <EmptyState type="error" onRetry={() => refetch()} />}
          {!isLoading && !isError && filtered.length === 0 && (
            <EmptyState type="empty" />
          )}

          {filtered.length > 0 && (
            <div className="divide-y divide-border-soft">
              {filtered.slice(0, 100).map((r) => {
                const labelDisp = r.label ? REVIEW_LABEL_DISPLAY[r.label as ReviewLabel] : null
                const variant = labelDisp?.color.replace("pill-", "") as
                  | "purple" | "teal" | "amber" | "blue" | "pink" | "red" | "green" | "gray" | undefined
                return (
                  <article key={r.id} className="px-3 py-2.5 text-xs">
                    <div className="flex items-baseline gap-2 flex-wrap mb-1">
                      <span className="font-medium">{r.competitor}</span>
                      <span className="text-2xs text-muted-foreground font-mono uppercase">{r.region_code}</span>
                      {r.score != null && <span className="text-2xs text-muted-foreground">{r.score}★</span>}
                      {r.version && <span className="text-2xs font-mono text-muted-foreground">{r.version}</span>}
                      {labelDisp && variant && (
                        <Pill variant={variant}>{labelDisp.text}</Pill>
                      )}
                      <span className="ml-auto text-2xs text-muted-foreground tabular-nums">
                        {r.at ? new Date(r.at).toLocaleDateString("zh-CN") : "—"}
                      </span>
                    </div>
                    {r.translated_text && (
                      <div className="leading-snug">{r.translated_text}</div>
                    )}
                    {r.content && r.content !== r.translated_text && (
                      <details className="mt-1">
                        <summary className="text-2xs text-muted-foreground cursor-pointer hover:text-foreground">原文</summary>
                        <p className="mt-1 text-2xs text-muted-foreground leading-snug">{r.content}</p>
                      </details>
                    )}
                    {r.entities && r.entities.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {r.entities.map((e, i) => {
                          const disp = ENTITY_TYPE_DISPLAY[e.type as EntityType]
                          return (
                            <span key={i} className="text-2xs px-1.5 h-5 inline-flex items-center rounded bg-muted/40 font-mono"
                              title={`${e.type} · ${e.canonical_id}`}>
                              {disp ? `${disp.prefix}${e.raw_value}` : e.raw_value}
                            </span>
                          )
                        })}
                      </div>
                    )}
                  </article>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
