/** 商业新闻页（spec 前端实现文档 §9.10 + wireframe 02）
 *
 * 改造点 vs v1:
 *  · 默认 is_business=true（task #5 news_classifier 过滤）
 *  · 按 5 桶分组展示（NEWS_BUCKETS 定义在 types/domain.ts）
 *  · KPI 卡内容向：真商业新闻数 / 涉及竞品 / 高优类别 / 7d 增量
 */
import { useMemo } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import FilterChips from "@/components/shared/FilterChips"
import EmptyState from "@/components/shared/EmptyState"
import Pill from "@/components/shared/Pill"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useNews } from "@/hooks/api/useNews"
import { useUrlFilters } from "@/hooks/useUrlFilters"
import {
  BASELINE_APP, COMPETITORS,
  NEWS_BUCKETS, BUSINESS_CATEGORY_LABELS,
} from "@/types/domain"
import type { NewsItem, BusinessCategory } from "@/types/api"
import { ExternalLink } from "lucide-react"

const TIME_OPTIONS = [
  { value: "24h", label: "今日" },
  { value: "7d",  label: "7d" },
  { value: "30d", label: "30d" },
]

const HIGH_PRIORITY: BusinessCategory[] = ["funding", "acquisition", "partnership"]

export default function News() {
  const { value, setValue } = useUrlFilters({
    since: "7d", competitor: "", bucket: "", show_all: "0",
  })
  const since = value("since")
  const competitor = value("competitor")
  const bucket = value("bucket")
  const showAll = value("show_all") === "1"

  const { data, isLoading, isError, refetch } = useNews({
    since,
    business_only: showAll ? 0 : 1,
    app: competitor || undefined,
    limit: 500,
  })
  const allNews = data?.news || []

  // 二次过滤（仅 bucket — 后端没有 bucket 概念，前端切）
  const filtered = useMemo(() => {
    return allNews.filter((n) => {
      if (bucket) {
        const b = NEWS_BUCKETS.find((x) => x.key === bucket)
        if (!b) return false
        if (!n.business_category || !b.categories.includes(n.business_category)) return false
      }
      return true
    })
  }, [allNews, bucket])

  // KPI（按 spec wireframe 02 的 4 张卡）
  const kpi = useMemo(() => {
    const total = filtered.length
    const apps = new Set(filtered.map((n) => n.app_name).filter(Boolean))
    const high = filtered.filter((n) =>
      n.business_category && HIGH_PRIORITY.includes(n.business_category)
    ).length
    return { total, apps: apps.size, high, since }
  }, [filtered, since])

  // 分桶
  const buckets = useMemo(() => {
    const out: Record<string, NewsItem[]> = {}
    for (const b of NEWS_BUCKETS) out[b.key] = []
    const noCategory: NewsItem[] = []
    for (const n of filtered) {
      const cat = n.business_category
      if (!cat) {
        noCategory.push(n)
        continue
      }
      const b = NEWS_BUCKETS.find((x) => x.categories.includes(cat))
      if (b) out[b.key].push(n)
      else noCategory.push(n)
    }
    return { out, noCategory }
  }, [filtered])

  return (
    <div>
      <PageHeader
        title="商业新闻"
        right={
          <span className="text-xs text-muted-foreground tabular-nums">
            共 {filtered.length} 条
          </span>
        }
      />

      <KpiRow>
        <KpiCard label={showAll ? "新闻数" : "真商业新闻"} value={kpi.total}
                 hint={`近 ${since}`} />
        <KpiCard label="涉及竞品" value={kpi.apps} />
        <KpiCard label="高优类别" value={kpi.high}
                 hint="融资 / 收购 / 合作" />
        <KpiCard label="AI 分类率"
                 value={allNews.length
                   ? `${Math.round(allNews.filter((n) => n.business_category).length / allNews.length * 100)}%`
                   : "—"}
                 hint={`${allNews.filter((n) => n.business_category).length}/${allNews.length}`} />
      </KpiRow>

      <div className="space-y-2 mb-3">
        <FilterChips label="时间" options={TIME_OPTIONS} value={since}
                     onChange={(v) => setValue("since", v)} />
        <FilterChips
          label="桶"
          options={[
            { value: "", label: "全部" },
            ...NEWS_BUCKETS.map((b) => ({ value: b.key, label: b.label })),
          ]}
          value={bucket}
          onChange={(v) => setValue("bucket", v)}
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
        <FilterChips
          label="模式"
          options={[
            { value: "0", label: "AI 过滤" },
            { value: "1", label: "全部新闻" },
          ]}
          value={showAll ? "1" : "0"}
          onChange={(v) => setValue("show_all", v)}
        />
      </div>

      {isLoading && <SkeletonTable rows={6} />}
      {isError && <EmptyState type="error" onRetry={() => refetch()} />}
      {!isLoading && !isError && filtered.length === 0 && (
        <EmptyState
          type="empty"
          hint={
            showAll
              ? "当前筛选下无新闻"
              : `近 ${since} 内无真商业新闻 — 放宽到 30d 或切到「全部新闻」看原始抓取结果`
          }
        />
      )}

      {filtered.length > 0 && (
        <div className="space-y-3">
          {NEWS_BUCKETS.map((b) => {
            const items = buckets.out[b.key] || []
            if (items.length === 0) return null
            return (
              <NewsBucketSection
                key={b.key}
                title={b.label}
                variant={b.variant}
                items={items}
                categoriesHint={b.categories.map((c) => BUSINESS_CATEGORY_LABELS[c]).join(" · ")}
              />
            )
          })}
          {/* 未分类 / fallback (showAll 时也展示) */}
          {buckets.noCategory.length > 0 && (
            <NewsBucketSection
              title={showAll ? "未分类 / 非商业" : "等待分类"}
              variant="gray"
              items={buckets.noCategory}
              categoriesHint={
                showAll
                  ? "包括比赛资讯 / 球员动态等非商业条目"
                  : "AI 还没跑过分类，或不属于 8 类标签"
              }
            />
          )}
        </div>
      )}
    </div>
  )
}

interface BucketProps {
  title: string
  variant: "amber" | "teal" | "blue" | "purple" | "gray"
  items: NewsItem[]
  categoriesHint: string
}

function NewsBucketSection({ title, variant, items, categoriesHint }: BucketProps) {
  return (
    <section className="border border-border-soft rounded-md bg-card overflow-hidden">
      <header className="flex items-center justify-between px-3 h-9 bg-muted/30 border-b border-border-soft">
        <div className="flex items-center gap-2">
          <Pill variant={variant}>{title}</Pill>
          <span className="text-2xs text-muted-foreground tabular-nums">{items.length} 条</span>
        </div>
        <span className="text-2xs text-muted-foreground font-mono">{categoriesHint}</span>
      </header>
      <div className="divide-y divide-border-soft">
        {items.map((n) => (
          <article
            key={n.id || n.url}
            className="px-3 py-2.5 hover:bg-muted/30 transition-colors duration-150"
          >
            <div className="flex items-baseline gap-2 mb-1">
              <span className="text-xs font-medium">{n.app_name || "—"}</span>
              {n.business_category && (
                <Pill variant={variant}>{BUSINESS_CATEGORY_LABELS[n.business_category]}</Pill>
              )}
              <span className="text-2xs text-muted-foreground font-mono">
                {n.source}
              </span>
              <span className="ml-auto text-2xs text-muted-foreground tabular-nums">
                {n.published_at ? new Date(n.published_at).toLocaleDateString("zh-CN") : "—"}
              </span>
            </div>
            <a
              href={n.url}
              target="_blank"
              rel="noreferrer"
              className="text-sm font-medium hover:text-brand-700 inline-flex items-baseline gap-1"
            >
              {n.title}
              <ExternalLink className="w-3 h-3 shrink-0" />
            </a>
            {n.snippet && (
              <p className="mt-1 text-xs text-muted-foreground line-clamp-2 leading-snug">
                {n.snippet}
              </p>
            )}
            {n.competitors_mentioned.length > 0 && (
              <div className="mt-1.5 flex items-center gap-1 flex-wrap">
                <span className="text-2xs text-muted-foreground">提及:</span>
                {n.competitors_mentioned.map((c) => (
                  <Pill key={c} variant="blue">{c}</Pill>
                ))}
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  )
}
