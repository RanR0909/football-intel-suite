/** 社媒评论页（spec 前端实现文档 §9.9）
 *
 * 改造点 vs v1:
 *  · 主视图改 5 tab：产品信号 / 热门话题 / 球员讨论 / 赛事讨论 / 产品提及
 *  · 数据 = /api/community-posts/aggregated（task #6 post_topic 输出聚合）
 *  · player / league dim 走 community_post_entities × entity_aliases (0016) —
 *    含主推竞品 + 共现实体（Top 5 同帖共现的其他实体）
 *  · 产品信号 tab = primary_topic IN (app_feature, app_bug, competitor_compare)
 *    按热度倒序原文列出，专供产品视角读取（非聚合）
 *  · 底部下钻：原始帖流（保留）
 */
import { useMemo } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import FilterChips from "@/components/shared/FilterChips"
import EmptyState from "@/components/shared/EmptyState"
import Pill from "@/components/shared/Pill"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useCommunity } from "@/hooks/api/useCommunity"
import { useCommunityAggregated } from "@/hooks/api/useAggregated"
import { useUrlFilters } from "@/hooks/useUrlFilters"
import { ArrowUp, MessageCircle, ExternalLink } from "lucide-react"
import { BASELINE_APP, COMPETITORS, POST_TOPIC_LABELS } from "@/types/domain"
import type {
  CommunityAggregatedDim, PostTopic,
  CommunityAggTopicRow, CommunityAggCompetitorRow, CommunityAggEntityRow,
} from "@/types/api"

/** 产品信号 = 这 3 类高价值主题：功能讨论 / 问题反馈 / 竞品对比。
 *  用户的"我只关心产品视角"诉求 — 跳过球员八卦和比赛汇总。 */
const PRODUCT_TOPICS: PostTopic[] = ["app_feature", "app_bug", "competitor_compare"]

/** 主视图维度。"product" 是非聚合 tab，单独路径渲染原文流；
 *  其他 4 个走 useCommunityAggregated。 */
type SocialTab = CommunityAggregatedDim | "product"

const TABS: Array<{ value: SocialTab; label: string }> = [
  { value: "topic",      label: "热门话题" },
  { value: "product",    label: "产品信号" },   // 用户最关注的核心 tab — 紧随总览
  { value: "player",     label: "球员讨论" },
  { value: "league",     label: "赛事讨论" },
  { value: "competitor", label: "产品提及" },
]

const SOURCE_OPTIONS = [
  { value: "", label: "全部" },
  { value: "reddit", label: "Reddit" },
  { value: "twitter", label: "Twitter" },
]

export default function Social() {
  const { value, setValue } = useUrlFilters({
    tab: "topic", source: "", competitor: "", since: "30d",
  })
  const tab = (value("tab") || "topic") as SocialTab
  const source = value("source") as "reddit" | "twitter" | ""
  const competitor = value("competitor")
  const since = value("since")

  // 总览原始帖（KPI + 底部下钻 + 产品信号 tab 的数据源）
  // 之前漏了 since — 导致 KPI 卡上写"近 ${since}"但实际是全时间窗口的 200 条
  const { data: rawPosts } = useCommunity({
    source: source || undefined, competitor, since, limit: 200,
  })
  const filteredPosts = useMemo(() => rawPosts?.posts || [], [rawPosts])

  // 产品信号子集 — 3 类高价值主题
  const productPosts = useMemo(() => {
    return filteredPosts
      .filter((p) => p.primary_topic && PRODUCT_TOPICS.includes(p.primary_topic))
      .sort((a, b) => (b.score || 0) - (a.score || 0))
  }, [filteredPosts])

  const kpi = useMemo(() => ({
    total: filteredPosts.length,
    productSignal: productPosts.length,
    reddit: filteredPosts.filter((p) => p.source === "reddit").length,
    hot: filteredPosts.filter((p) => (p.score || 0) >= 100).length,
  }), [filteredPosts, productPosts])

  return (
    <div>
      <PageHeader
        title="社媒评论"
        subtitle="Reddit + Twitter · 按主题 / 球员 / 联赛 / 产品聚合"
      />

      <KpiRow>
        <KpiCard label="总帖子数" value={kpi.total} hint={`近 ${since}`} />
        <KpiCard
          label="产品信号"
          value={kpi.productSignal}
          hint="功能 / 问题 / 竞品对比"
        />
        <KpiCard label="Reddit" value={kpi.reddit} />
        <KpiCard label="高热（≥100）" value={kpi.hot} />
      </KpiRow>

      <div className="space-y-2 mb-3">
        <FilterChips
          label="维度"
          options={TABS.map((t) => ({ value: t.value, label: t.label }))}
          value={tab}
          onChange={(v) => setValue("tab", v)}
        />
        <FilterChips label="平台" options={SOURCE_OPTIONS} value={source}
                     onChange={(v) => setValue("source", v)} />
        <FilterChips
          label="时间"
          options={[
            { value: "7d",  label: "7d" },
            { value: "30d", label: "30d" },
            { value: "90d", label: "90d" },
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

      {tab === "product" ? (
        <ProductSignalsTab posts={productPosts} />
      ) : (
        <AggregatedTab dim={tab} since={since} />
      )}

      {/* 底部下钻：原始帖流（按热度排序） */}
      <details className="mt-6">
        <summary className="text-2xs uppercase tracking-wider text-muted-foreground cursor-pointer mb-2">
          原始帖流（{filteredPosts.length} 条）
        </summary>
        {filteredPosts.length === 0 ? (
          <EmptyState type="empty" />
        ) : (
          <div className="space-y-1">
            {filteredPosts.slice(0, 50).map((p) => (
              <article key={p.id} className="border border-border-soft rounded-md bg-card px-3 py-2">
                <div className="flex items-baseline gap-2 mb-1 text-2xs">
                  <Pill variant={p.source === "reddit" ? "amber" : "blue"}>{p.source}</Pill>
                  {p.subreddit && <span className="font-mono text-muted-foreground">{p.subreddit}</span>}
                  <span className="font-medium">{p.competitor}</span>
                  {p.primary_topic && (
                    <Pill variant="purple">{POST_TOPIC_LABELS[p.primary_topic] || p.primary_topic}</Pill>
                  )}
                  <span className="ml-auto inline-flex items-center gap-2 font-mono text-muted-foreground">
                    {p.score != null && <span><ArrowUp className="w-3 h-3 inline -mt-0.5" />{p.score}</span>}
                    {p.num_comments != null && <span><MessageCircle className="w-3 h-3 inline -mt-0.5" />{p.num_comments}</span>}
                  </span>
                </div>
                {p.url ? (
                  <a href={p.url} target="_blank" rel="noreferrer"
                     className="text-xs font-medium hover:text-brand-700 inline-flex items-baseline gap-1">
                    {p.title || "(no title)"}
                    <ExternalLink className="w-3 h-3 shrink-0" />
                  </a>
                ) : (
                  <div className="text-xs font-medium">{p.title || "(no title)"}</div>
                )}
              </article>
            ))}
          </div>
        )}
      </details>
    </div>
  )
}

// ─────────── 产品信号 tab — 帖子原文流（按热度排序） ───────────
//
// 跟其他 4 个 tab 不同：这里不是聚合，是直接列原文。用户视角："我只想读
// 跟我们产品 / 竞品产品有关的讨论，跳过球员八卦和比赛汇总"。
//
// 数据 = 父组件的 productPosts（filteredPosts 里 primary_topic ∈ PRODUCT_TOPICS
// 子集，按 score 倒序）

const TOPIC_PILL_VARIANT: Partial<Record<PostTopic, "teal" | "red" | "amber">> = {
  app_feature: "teal",        // 功能讨论 — 中性绿
  app_bug: "red",             // 问题反馈 — 红
  competitor_compare: "amber", // 竞品对比 — 橙
}

function ProductSignalsTab({ posts }: { posts: ReturnType<typeof useCommunity>["data"] extends infer T
                                                 ? T extends { posts: infer R } ? R : never
                                                 : never }) {
  if (!posts || posts.length === 0) {
    return (
      <EmptyState
        type="empty"
        hint="近窗口内 0 条产品信号 — 放宽时间或检查 task #6 (post_topic) 是否跑过"
      />
    )
  }
  return (
    <div className="space-y-2">
      {/* 按 topic 分组 */}
      {(["app_feature", "app_bug", "competitor_compare"] as const).map((tp) => {
        const subset = posts.filter((p) => p.primary_topic === tp)
        if (subset.length === 0) return null
        return (
          <section key={tp} className="border border-border-soft rounded-md bg-card overflow-hidden">
            <header className="flex items-center justify-between px-3 h-9 bg-muted/30 border-b border-border-soft">
              <div className="flex items-center gap-2">
                <Pill variant={TOPIC_PILL_VARIANT[tp] || "purple"}>
                  {POST_TOPIC_LABELS[tp]}
                </Pill>
                <span className="text-2xs text-muted-foreground tabular-nums">{subset.length} 条</span>
              </div>
              <span className="text-2xs font-mono text-muted-foreground">{tp}</span>
            </header>
            <div className="divide-y divide-border-soft">
              {subset.slice(0, 30).map((p) => (
                <article key={p.id} className="px-3 py-2.5 hover:bg-muted/30 transition-colors duration-150">
                  <div className="flex items-baseline gap-2 mb-1 text-2xs flex-wrap">
                    <Pill variant={p.source === "reddit" ? "amber" : "blue"}>{p.source}</Pill>
                    {p.subreddit && (
                      <span className="font-mono text-muted-foreground">{p.subreddit}</span>
                    )}
                    {p.competitor_mentioned && (
                      <Pill variant="purple">{p.competitor_mentioned}</Pill>
                    )}
                    {/* 次主题 */}
                    {(p.secondary_topics || []).slice(0, 2).map((st) => (
                      <span key={st} className="text-2xs text-muted-foreground italic">
                        +{POST_TOPIC_LABELS[st] || st}
                      </span>
                    ))}
                    <span className="ml-auto inline-flex items-center gap-2 font-mono text-muted-foreground">
                      {p.score != null && (
                        <span><ArrowUp className="w-3 h-3 inline -mt-0.5" />{p.score}</span>
                      )}
                      {p.num_comments != null && (
                        <span><MessageCircle className="w-3 h-3 inline -mt-0.5" />{p.num_comments}</span>
                      )}
                    </span>
                  </div>
                  {p.url ? (
                    <a
                      href={p.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-sm font-medium hover:text-brand-700 inline-flex items-baseline gap-1 leading-snug"
                    >
                      {p.title || "(no title)"}
                      <ExternalLink className="w-3 h-3 shrink-0" />
                    </a>
                  ) : (
                    <div className="text-sm font-medium leading-snug">{p.title || "(no title)"}</div>
                  )}
                  {p.selftext && (
                    <p className="mt-1 text-xs text-muted-foreground line-clamp-3 leading-snug">
                      {p.selftext}
                    </p>
                  )}
                </article>
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}

function AggregatedTab({ dim, since }: { dim: CommunityAggregatedDim; since: string }) {
  const { data, isLoading, isError, refetch } = useCommunityAggregated(dim, { since, limit: 50 })

  if (isLoading) return <SkeletonTable rows={5} />
  if (isError) return <EmptyState type="error" onRetry={() => refetch()} />
  const items = data?.items || []
  if (!items.length) {
    return (
      <EmptyState
        type="empty"
        hint={data?.hint || "task #6 post_topic 还未在该维度产出结果"}
      />
    )
  }

  if (dim === "topic") {
    const rows = items as CommunityAggTopicRow[]
    return (
      <div className="border border-border-soft rounded-md bg-card overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-muted/30">
            <tr className="text-2xs uppercase tracking-wider text-muted-foreground">
              <th className="text-left  px-3 h-8">话题</th>
              <th className="text-right px-3 h-8 tabular-nums">帖数</th>
              <th className="text-right px-3 h-8 tabular-nums">总热度</th>
              <th className="text-right px-3 h-8 tabular-nums">涉及竞品数</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.topic} className="border-t border-border-soft hover:bg-muted/30">
                <td className="px-3 py-2">
                  <Pill variant="purple">{POST_TOPIC_LABELS[r.topic] || r.topic}</Pill>
                  <span className="ml-1 font-mono text-2xs text-muted-foreground">{r.topic}</span>
                </td>
                <td className="text-right px-3 py-2 tabular-nums font-mono">{r.post_count}</td>
                <td className="text-right px-3 py-2 tabular-nums font-mono">{r.total_score}</td>
                <td className="text-right px-3 py-2 tabular-nums font-mono">{r.comp_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  if (dim === "competitor") {
    const rows = items as CommunityAggCompetitorRow[]
    return (
      <div className="border border-border-soft rounded-md bg-card overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-muted/30">
            <tr className="text-2xs uppercase tracking-wider text-muted-foreground">
              <th className="text-left  px-3 h-8">竞品</th>
              <th className="text-right px-3 h-8 tabular-nums">提及帖数</th>
              <th className="text-right px-3 h-8 tabular-nums">总热度</th>
              <th className="text-left  px-3 h-8">主要话题 Top 3</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.competitor} className="border-t border-border-soft hover:bg-muted/30">
                <td className="px-3 py-2 font-medium">{r.competitor}</td>
                <td className="text-right px-3 py-2 tabular-nums font-mono">{r.post_count}</td>
                <td className="text-right px-3 py-2 tabular-nums font-mono">{r.total_score}</td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    {(r.top_topics || []).map((t) => (
                      <Pill key={t.topic} variant="purple">
                        {POST_TOPIC_LABELS[t.topic] || t.topic} {t.n}
                      </Pill>
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

  // player / league — community_post_entities × entity_aliases
  if (dim === "player" || dim === "league") {
    const rows = items as CommunityAggEntityRow[]
    return (
      <div className="border border-border-soft rounded-md bg-card overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-muted/30">
            <tr className="text-2xs uppercase tracking-wider text-muted-foreground">
              <th className="text-left  px-3 h-8">{dim === "player" ? "球员" : "联赛"}</th>
              <th className="text-right px-3 h-8 tabular-nums">提及帖数</th>
              <th className="text-right px-3 h-8 tabular-nums">总热度</th>
              <th className="text-left  px-3 h-8">主推竞品 Top 3</th>
              <th className="text-left  px-3 h-8">高频共现</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.canonical_id} className="border-t border-border-soft hover:bg-muted/30">
                <td className="px-3 py-2">
                  <span className="font-medium">{r.primary_name}</span>
                  <span className="ml-1 font-mono text-2xs text-muted-foreground">{r.canonical_id}</span>
                </td>
                <td className="text-right px-3 py-2 tabular-nums font-mono">{r.post_count}</td>
                <td className="text-right px-3 py-2 tabular-nums font-mono">{r.total_score}</td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    {(r.top_competitors || []).map((c) => (
                      <Pill key={c.competitor} variant="blue">{c.competitor} {c.n}</Pill>
                    ))}
                  </div>
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    {(r.cooccurring || []).slice(0, 5).map((co) => (
                      <Pill key={co.name} variant="gray">{co.name}<span className="text-2xs ml-0.5 opacity-60">·{co.etype}</span></Pill>
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

  return <EmptyState type="empty" hint={data?.hint || "暂未实现"} />
}
