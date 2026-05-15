/** GP 评论页（spec 前端实现文档 §9.8 + wireframe 01）
 *
 * 改造点 vs v1:
 *  · 主视图改 5 tab：问题 Top / 问题原文 / 好评 Top / 本地化 / 竞品流向
 *  · 聚合 tab 走 /api/reviews/aggregated?tab=… (按 entity 聚合)
 *  · "问题原文" tab = label='complaint' 评论原帖流，按差评分组按竞品分桶
 *    (类似社媒"产品信号"，给产品视角直接读用户抱怨原文)
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

/** "top" = 前端合成 (problems + praise 按 total_mentions desc)；
 *  "raw_problems" = 非聚合 tab，直接列 complaint 评论原文（≤2 星优先）；
 *  其他 4 个直接走 useReviewsAggregated。 */
type GPTab = "top" | ReviewsAggregatedTab | "raw_problems"

/** 拼商店页 URL —— GP/iOS 评论都没存 review_id，只能跳到 app 商店页（带 region）。
 *  GP: play.google.com/store/apps/details?id=PACKAGE&gl=US
 *  iOS: apps.apple.com/us/app/idXXX  */
function storeUrl(
  platform: "gp" | "ios" | null | undefined,
  gpPackage: string | null | undefined,
  iosAppId: string | null | undefined,
  region: string | null | undefined,
): string | null {
  const gl = (region || "us").toUpperCase()
  if (platform === "gp" && gpPackage) {
    return `https://play.google.com/store/apps/details?id=${gpPackage}&gl=${gl}`
  }
  if (platform === "ios" && iosAppId) {
    return `https://apps.apple.com/${gl.toLowerCase()}/app/id${iosAppId}`
  }
  return null
}

const TABS: Array<{ value: GPTab; label: string }> = [
  { value: "top",           label: "讨论 Top" },   // 问题 + 好评 合并按提及降序
  { value: "problems",      label: "问题 Top" },
  { value: "raw_problems",  label: "问题原文" },   // 用户重点：直接读差评原文
  { value: "praise",        label: "好评 Top" },
  { value: "localization",  label: "本地化" },
  { value: "churn",         label: "竞品流向" },
]

const LABEL_KEYS: ReviewLabel[] = [
  "complaint", "feature_request", "competitor_compare",
  "churn_signal", "positive", "other",
]

export default function GPReviews() {
  const { value, setValue } = useUrlFilters({
    tab: "top", competitor: "", since: "7d",
  })
  const tab = (value("tab") || "top") as GPTab
  const competitor = value("competitor")
  const since = value("since")

  // 主聚合数据。
  // top tab 合成自 problems + praise 两份；raw_problems tab 不用单独聚合（走 raw reviews）；
  // 其他 4 个 tab 直接拉对应的 aggregated。
  const aggTab: ReviewsAggregatedTab =
    tab === "raw_problems" ? "problems" :
    tab === "top" ? "problems" : tab
  const { data: agg, isLoading, isError, refetch } = useReviewsAggregated(aggTab, 30)
  // top tab 额外拿 praise（problems 已经走 agg；二者合并）
  const { data: aggPraiseForTop } = useReviewsAggregated("praise", 30)
  const topItems = useMemo(() => {
    if (tab !== "top") return [] as Array<ReviewsAggregatedResponse["items"][number] & { _kind: "problem" | "praise" }>
    const merged: Array<ReviewsAggregatedResponse["items"][number] & { _kind: "problem" | "praise" }> = []
    for (const it of agg?.items || []) merged.push({ ...it, _kind: "problem" })
    for (const it of aggPraiseForTop?.items || []) merged.push({ ...it, _kind: "praise" })
    merged.sort((a, b) => b.total_mentions - a.total_mentions)
    return merged.slice(0, 30)
  }, [tab, agg, aggPraiseForTop])

  // 用于 KPI 计算和底部矩阵的原始 reviews
  // raw_problems tab 同时拿 label='complaint' 的全量原文（最多 1000 条）
  const { data: rawReviews } = useReviews({
    competitor: competitor || undefined,
    label: tab === "raw_problems" ? "complaint" : undefined,
    since, limit: 1000,
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

      {tab === "raw_problems" ? (
        <RawProblemsTab reviews={allReviews} />
      ) : tab === "top" ? (
        <>
          {isLoading && <SkeletonTable rows={6} />}
          {isError && <EmptyState type="error" onRetry={() => refetch()} />}
          {!isLoading && !isError && topItems.length === 0 && (
            <EmptyState type="empty" hint="entity_extract 还未产出 problem / praise 主题" />
          )}
          {topItems.length > 0 && <AggregatedList items={topItems} tab="problems" showKind />}
        </>
      ) : (
        <>
          {isLoading && <SkeletonTable rows={6} />}
          {isError && <EmptyState type="error" onRetry={() => refetch()} />}
          {!isLoading && !isError && (!agg || agg.items.length === 0) && (
            <EmptyState type="empty" hint="entity_extract 还未在该维度产出结果" />
          )}

          {agg && agg.items.length > 0 && (
            <AggregatedList items={agg.items} tab={aggTab} />
          )}
        </>
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
  items, tab, showKind = false,
}: {
  items: Array<ReviewsAggregatedResponse["items"][number] & { _kind?: "problem" | "praise" }>;
  tab: ReviewsAggregatedTab;
  showKind?: boolean;
}) {
  return (
    <div className="space-y-2">
      {items.map((it) => (
        <article key={`${it._kind ?? ""}:${it.canonical_id}`} className="border border-border-soft rounded-md bg-card overflow-hidden">
          <header className="flex items-baseline gap-2 px-3 h-9 bg-muted/30 border-b border-border-soft">
            {showKind && it._kind && (
              <Pill variant={it._kind === "problem" ? "red" : "green"}>
                {it._kind === "problem" ? "问题" : "好评"}
              </Pill>
            )}
            {/* 中文翻译优先；翻译过的同时把原文小字附在后面便于交叉确认 */}
            <span className="text-sm font-medium">
              {it.chinese_name || it.primary_name}
            </span>
            {it.chinese_name && it.chinese_name !== it.primary_name && (
              <span className="text-2xs text-muted-foreground italic">
                ({it.primary_name})
              </span>
            )}
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
                <div className="mt-1 text-2xs text-muted-foreground flex items-center gap-2 flex-wrap">
                  <span>
                    {it.representative_review.competitor} · {it.representative_review.region?.toUpperCase()}
                    {it.representative_review.score != null && ` · ${it.representative_review.score}★`}
                  </span>
                  {(() => {
                    const url = storeUrl(
                      it.representative_review.platform,
                      it.representative_review.gp_package,
                      it.representative_review.ios_app_id,
                      it.representative_review.region,
                    )
                    return url ? (
                      <a
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary hover:underline"
                        title="跳到商店页（无法定位到单条评论 — DB 未保存原 review_id）"
                      >
                        商店页 →
                      </a>
                    ) : null
                  })()}
                </div>
              )}
            </div>
          </div>
        </article>
      ))}
      {items.length === 30 && (
        <div className="text-2xs text-center text-muted-foreground py-2">
          已显示前 30 个{showKind ? "讨论" : tab}主题
        </div>
      )}
    </div>
  )
}

// ─────────── 问题原文 tab — complaint 类评论按差评分组 ───────────
//
// 跟"问题 Top" tab (entity 聚合) 的关系：
//   · 问题 Top    → 看"哪几类 bug 提及次数最多"（产品全局视角）
//   · 问题原文    → 看"具体每个 1 星 / 2 星用户在抱怨什么"（产品具体反馈）
//
// 后端去重：(competitor, platform, content, score, version) GROUP BY，
// 同一英文 GP 评论在 12 国出现的 12 条 → 合成 1 条 + regions=["GB","CA",...]
//
// 默认每个 score section 折叠（用 <details>）— 1 星 174 条 / 2 星 82 条
// 全部展开太长。点击 header 展开看全部（不再做 30 条截断）。

const SCORE_VARIANT: Record<string, "red" | "amber" | "gray" | "green"> = {
  "1": "red", "2": "red", "3": "amber", "4": "gray", "5": "green", "?": "gray",
}
const SCORE_LABELS: Record<string, string> = {
  "1": "1 ★ 极差", "2": "2 ★ 差", "3": "3 ★ 中", "4": "4 ★ 良", "5": "5 ★ 优", "?": "无评分",
}

function RawProblemsTab({ reviews }: { reviews: any[] }) {
  const grouped = useMemo(() => {
    // 按 score 分桶（1 / 2 / 3 / 4 / 5 / null）+ 同桶内按 at desc
    const buckets: Record<string, any[]> = { "1": [], "2": [], "3": [], "4": [], "5": [], "?": [] }
    for (const r of reviews) {
      const k = r.score == null ? "?" : String(r.score)
      if (!buckets[k]) buckets[k] = []
      buckets[k].push(r)
    }
    for (const k of Object.keys(buckets)) {
      buckets[k].sort((a, b) => (b.at || "").localeCompare(a.at || ""))
    }
    return buckets
  }, [reviews])

  if (!reviews || reviews.length === 0) {
    return (
      <EmptyState
        type="empty"
        hint="近窗口内 0 条 complaint 评论 — 放宽时间或换一个竞品"
      />
    )
  }

  const totalPosts = reviews.length

  return (
    <div className="space-y-2">
      <div className="text-2xs text-muted-foreground px-1">
        共 {totalPosts} 条 (已按内容去重；同一评论在多区域出现合并显示)
      </div>
      {(["1", "2", "3", "4", "5", "?"] as const).map((sc) => {
        const subset = grouped[sc] || []
        if (subset.length === 0) return null
        // 1 星默认展开（最重要）；其他默认折叠
        const defaultOpen = sc === "1"
        return (
          <details
            key={sc}
            open={defaultOpen}
            className="border border-border-soft rounded-md bg-card overflow-hidden group"
          >
            <summary
              className="flex items-center justify-between px-3 h-9 bg-muted/30 border-b border-border-soft cursor-pointer list-none hover:bg-muted/50"
            >
              <div className="flex items-center gap-2">
                <span className="text-2xs text-muted-foreground group-open:rotate-90 inline-block transition-transform">▶</span>
                <Pill variant={SCORE_VARIANT[sc] || "gray"}>{SCORE_LABELS[sc]}</Pill>
                <span className="text-2xs text-muted-foreground tabular-nums">{subset.length} 条</span>
              </div>
            </summary>
            <div className="divide-y divide-border-soft">
              {subset.map((r) => {
                const regions = r.regions && r.regions.length > 0
                  ? r.regions
                  : (r.region_code ? [r.region_code] : [])
                return (
                  <article key={r.id} className="px-3 py-2.5 hover:bg-muted/30 transition-colors duration-150">
                    <div className="flex items-baseline gap-2 mb-1 text-2xs flex-wrap">
                      <span className="font-medium">{r.competitor}</span>
                      {/* 多区域 chip — 同一评论命中几个国家就展示几个 */}
                      {regions.length === 1 ? (
                        <Pill variant="gray">{regions[0].toUpperCase()}</Pill>
                      ) : regions.length <= 3 ? (
                        <Pill variant="gray">{regions.map((x: string) => x.toUpperCase()).join(" · ")}</Pill>
                      ) : (
                        <Pill variant="gray" className="font-mono">
                          {regions.length} 国 ({regions.slice(0, 3).map((x: string) => x.toUpperCase()).join(" · ")} +{regions.length - 3})
                        </Pill>
                      )}
                      <Pill variant="blue">{r.platform}</Pill>
                      {r.version && (
                        <span className="font-mono text-muted-foreground">v{r.version}</span>
                      )}
                      {(() => {
                        const url = storeUrl(
                          r.platform,
                          r.gp_package,
                          r.ios_app_id,
                          regions[0] || r.region_code,
                        )
                        return url ? (
                          <a
                            href={url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-primary hover:underline"
                            title="跳到商店页（无法定位到单条评论）"
                          >
                            商店页 →
                          </a>
                        ) : null
                      })()}
                      <span className="ml-auto font-mono text-muted-foreground tabular-nums">
                        {r.at ? new Date(r.at).toLocaleDateString("zh-CN") : "—"}
                      </span>
                    </div>
                    <p className="text-xs leading-snug text-foreground">
                      {r.translated_text || r.content}
                    </p>
                    {r.translated_text && r.content && r.translated_text !== r.content && (
                      <details className="mt-1 text-2xs text-muted-foreground">
                        <summary className="cursor-pointer">原文 ({r.language || "?"})</summary>
                        <p className="mt-1 italic leading-snug">{r.content}</p>
                      </details>
                    )}
                  </article>
                )
              })}
            </div>
          </details>
        )
      })}
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
