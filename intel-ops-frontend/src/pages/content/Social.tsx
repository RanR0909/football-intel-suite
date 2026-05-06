/** 社媒评论页（spec 前端实现文档 §9.9）
 *
 * 改造点 vs v1:
 *  · 主视图改 4 tab：热门话题 / 球员讨论 / 赛事讨论 / 产品提及
 *  · 数据 = /api/community-posts/aggregated（task #6 post_topic 输出聚合）
 *  · player / league dim 后端尚未实现 entity_extract on community_posts，
 *    会返回 hint — 前端展示提示而不是空白
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
  CommunityAggregatedDim,
  CommunityAggTopicRow, CommunityAggCompetitorRow,
} from "@/types/api"

const TABS: Array<{ value: CommunityAggregatedDim; label: string }> = [
  { value: "topic",      label: "热门话题" },
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
  const tab = (value("tab") || "topic") as CommunityAggregatedDim
  const source = value("source") as "reddit" | "twitter" | ""
  const competitor = value("competitor")
  const since = value("since")

  // 总览原始帖（KPI + 底部下钻）
  const { data: rawPosts } = useCommunity({
    source: source || undefined, competitor, limit: 200,
  })
  const filteredPosts = useMemo(() => rawPosts?.posts || [], [rawPosts])

  const kpi = useMemo(() => ({
    total: filteredPosts.length,
    reddit: filteredPosts.filter((p) => p.source === "reddit").length,
    twitter: filteredPosts.filter((p) => p.source === "twitter").length,
    hot: filteredPosts.filter((p) => (p.score || 0) >= 100).length,
  }), [filteredPosts])

  return (
    <div>
      <PageHeader
        title="社媒评论"
        subtitle="Reddit + Twitter · 按主题 / 球员 / 联赛 / 产品聚合"
      />

      <KpiRow>
        <KpiCard label="总帖子数" value={kpi.total} hint={`近 ${since}`} />
        <KpiCard label="Reddit" value={kpi.reddit} />
        <KpiCard label="Twitter" value={kpi.twitter} />
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

      <AggregatedTab dim={tab} since={since} />

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

  // player / league — 后端 hint 路径
  return <EmptyState type="empty" hint={data?.hint || "暂未实现"} />
}
