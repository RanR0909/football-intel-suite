/** GP 评论页（spec 前端实现文档 §9.8 + wireframe 01）
 *
 * 改造点 vs v1:
 *  · 主视图改 4 tab：问题 Top / 好评 Top / 本地化 / 竞品流向
 *  · 每 tab 走 /api/reviews/aggregated?tab=… (按 entity 聚合)
 *  · KPI 改"内容向"：总评论数 / 最热问题 / 最热请求功能 / 主要流向竞品
 *  · 底部保留 6 类标签矩阵作下钻
 */
import { useMemo } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import FilterChips from "@/components/shared/FilterChips"
import EmptyState from "@/components/shared/EmptyState"
import Pill from "@/components/shared/Pill"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useReviews } from "@/hooks/api/useReviews"
import { useReviewsAggregated } from "@/hooks/api/useAggregated"
import { useUrlFilters } from "@/hooks/useUrlFilters"
import {
  BASELINE_APP, COMPETITORS, REVIEW_LABEL_DISPLAY,
} from "@/types/domain"
import type { ReviewLabel, ReviewsAggregatedTab, ReviewsAggregatedResponse } from "@/types/api"

const TABS: Array<{ value: ReviewsAggregatedTab; label: string }> = [
  { value: "problems",     label: "问题 Top" },
  { value: "praise",       label: "好评 Top" },
  { value: "localization", label: "本地化" },
  { value: "churn",        label: "竞品流向" },
]

const LABEL_KEYS: ReviewLabel[] = [
  "complaint", "feature_request", "competitor_compare",
  "churn_signal", "positive", "other",
]

export default function GPReviews() {
  const { value, setValue } = useUrlFilters({
    tab: "problems", competitor: "", since: "7d",
  })
  const tab = (value("tab") || "problems") as ReviewsAggregatedTab
  const competitor = value("competitor")
  const since = value("since")

  // 主聚合数据（每个 tab）
  const { data: agg, isLoading, isError, refetch } = useReviewsAggregated(tab, 30)

  // 用于 KPI 计算和底部矩阵的原始 reviews
  const { data: rawReviews } = useReviews({
    competitor: competitor || undefined, since, limit: 500,
  })
  const allReviews = useMemo(() => rawReviews?.reviews || [], [rawReviews])

  // KPI（top 1 of 3 关键 tab）
  const { data: aggProblems } = useReviewsAggregated("problems", 1)
  const { data: aggPraise }   = useReviewsAggregated("praise", 1)
  const { data: aggChurn }    = useReviewsAggregated("churn", 1)

  return (
    <div>
      <PageHeader
        title="GP 评论"
        subtitle="用户在抱怨什么 / 喜欢什么 / 本地化做得怎样"
        right={
          agg && (
            <span className="text-xs text-muted-foreground tabular-nums">
              {tab} · {agg.count} 主题
            </span>
          )
        }
      />

      <KpiRow>
        <KpiCard
          label="总评论数"
          value={allReviews.length || "—"}
          hint={`近 ${since} · ${COMPETITORS.length} 竞品`}
        />
        <KpiTopEntity label="最热问题"     resp={aggProblems} />
        <KpiTopEntity label="最热请求功能" resp={aggPraise} />
        <KpiTopEntity label="主要流向竞品" resp={aggChurn} prefix="→ " />
      </KpiRow>

      <div className="space-y-2 mb-3">
        <FilterChips
          label="维度"
          options={TABS.map((t) => ({ value: t.value, label: t.label }))}
          value={tab}
          onChange={(v) => setValue("tab", v)}
        />
        <FilterChips
          label="时间"
          options={[
            { value: "24h", label: "24h" },
            { value: "3d",  label: "3d" },
            { value: "7d",  label: "7d" },
            { value: "30d", label: "30d" },
          ]}
          value={since}
          onChange={(v) => setValue("since", v)}
        />
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

      {isLoading && <SkeletonTable rows={6} />}
      {isError && <EmptyState type="error" onRetry={() => refetch()} />}
      {!isLoading && !isError && (!agg || agg.items.length === 0) && (
        <EmptyState type="empty" hint="entity_extract 还未在该维度产出结果" />
      )}

      {agg && agg.items.length > 0 && (
        <AggregatedList items={agg.items} tab={tab} />
      )}

      {/* 底部下钻：6 类标签矩阵 */}
      <details className="mt-6">
        <summary className="text-2xs uppercase tracking-wider text-muted-foreground cursor-pointer mb-2">
          查看 6 类标签矩阵
        </summary>
        <LabelMatrix reviews={allReviews} />
      </details>
    </div>
  )
}

function KpiTopEntity({ label, resp, prefix = "" }: {
  label: string; resp?: ReviewsAggregatedResponse | undefined; prefix?: string
}) {
  const i = resp?.items?.[0]
  return (
    <KpiCard
      label={label}
      value={i ? <span>{prefix}{i.primary_name}</span> : "—"}
      hint={i ? `${i.total_mentions} 提及` : ""}
    />
  )
}

function AggregatedList({
  items, tab,
}: { items: ReviewsAggregatedResponse["items"]; tab: ReviewsAggregatedTab }) {
  return (
    <div className="space-y-2">
      {items.map((it) => (
        <article key={it.canonical_id} className="border border-border-soft rounded-md bg-card overflow-hidden">
          <header className="flex items-baseline gap-2 px-3 h-9 bg-muted/30 border-b border-border-soft">
            <span className="text-sm font-medium">{it.primary_name}</span>
            <span className="text-2xs text-muted-foreground font-mono">{it.canonical_id}</span>
            <span className="ml-auto text-2xs font-mono tabular-nums">
              {it.total_mentions} 提及
            </span>
          </header>
          <div className="px-3 py-2 grid grid-cols-1 md:grid-cols-3 gap-3 text-2xs">
            <div>
              <div className="uppercase tracking-wider text-muted-foreground mb-1">涉及竞品</div>
              <div className="flex flex-wrap gap-1">
                {Object.entries(it.by_competitor || {})
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 5)
                  .map(([c, n]) => (
                    <Pill key={c} variant="blue">{c} {n}</Pill>
                  ))}
              </div>
            </div>
            <div>
              <div className="uppercase tracking-wider text-muted-foreground mb-1">主要区域</div>
              <div className="flex flex-wrap gap-1 font-mono">
                {Object.entries(it.by_region || {})
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 4)
                  .map(([r, n]) => (
                    <Pill key={r} variant="gray">{r} · {n}</Pill>
                  ))}
              </div>
            </div>
            <div>
              <div className="uppercase tracking-wider text-muted-foreground mb-1">代表原文</div>
              <div className="text-xs leading-snug text-foreground/80 line-clamp-3">
                {it.representative_review?.text_zh || "—"}
              </div>
              {it.representative_review && (
                <div className="mt-1 text-2xs text-muted-foreground">
                  {it.representative_review.competitor} · {it.representative_review.region?.toUpperCase()}
                  {it.representative_review.score != null && ` · ${it.representative_review.score}★`}
                </div>
              )}
            </div>
          </div>
        </article>
      ))}
      {items.length === 30 && (
        <div className="text-2xs text-center text-muted-foreground py-2">
          已显示前 30 个 {tab} 主题
        </div>
      )}
    </div>
  )
}

function LabelMatrix({ reviews }: { reviews: any[] }) {
  const matrix = useMemo(() => {
    const m: Record<string, Record<ReviewLabel, number>> = {}
    for (const app of COMPETITORS) {
      m[app] = {
        complaint: 0, feature_request: 0, competitor_compare: 0,
        churn_signal: 0, positive: 0, other: 0,
      }
    }
    for (const r of reviews || []) {
      if (!m[r.competitor]) continue
      const lbl = (r.label || "other") as ReviewLabel
      m[r.competitor][lbl] = (m[r.competitor][lbl] || 0) + 1
    }
    return m
  }, [reviews])

  return (
    <div className="border border-border-soft rounded-md bg-card overflow-x-auto">
      <table className="w-full text-2xs">
        <thead className="bg-muted/30">
          <tr>
            <th className="text-left px-3 h-8 uppercase tracking-wider text-muted-foreground">竞品</th>
            {LABEL_KEYS.map((k) => (
              <th key={k} className="text-right px-2 h-8 uppercase tracking-wider text-muted-foreground">
                {REVIEW_LABEL_DISPLAY[k].text}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {COMPETITORS.map((app) => (
            <tr key={app} className="border-t border-border-soft hover:bg-muted/30">
              <td className="px-3 py-1.5 font-medium">{app}</td>
              {LABEL_KEYS.map((k) => (
                <td key={k} className="text-right px-2 py-1.5 tabular-nums font-mono">
                  {matrix[app][k] || "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
