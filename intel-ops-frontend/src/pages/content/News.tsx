import { useMemo } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import FilterChips from "@/components/shared/FilterChips"
import AppScopeChip from "@/components/shared/AppScopeChip"
import EmptyState from "@/components/shared/EmptyState"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useNews } from "@/hooks/api/useNews"
import { useUrlFilters } from "@/hooks/useUrlFilters"
import { useFilterStore } from "@/stores/filterStore"
import { BASELINE_APP, COMPETITORS } from "@/types/domain"
import { ExternalLink } from "lucide-react"

const TIME_OPTIONS = [
  { value: "24h", label: "今日" },
  { value: "7d", label: "7d" },
  { value: "30d", label: "30d" },
]

const KEYWORDS = ["funding", "acquires", "acquisition", "launches", "partnership", "deal", "revenue"]

export default function News() {
  const { value, setValue } = useUrlFilters({
    since: "7d", competitor: "", keyword: "",
  })
  const since = value("since")
  const competitor = value("competitor")
  const keyword = value("keyword").toLowerCase()
  const { appScope } = useFilterStore()

  const { data, isLoading, isError, refetch } = useNews({ since, limit: 500 })
  const allNews = data?.news || []

  // 客户端二次过滤
  const filtered = useMemo(() => {
    return allNews.filter((n) => {
      // app scope
      if (appScope === "competitor" && n.competitor === BASELINE_APP) return false
      if (appScope === "baseline" && n.competitor !== BASELINE_APP) return false
      // 竞品筛选
      if (competitor && n.competitor !== competitor) return false
      // 关键词
      if (keyword) {
        const haystack = `${n.title || ""} ${n.desc || ""}`.toLowerCase()
        if (!haystack.includes(keyword)) return false
      }
      return true
    })
  }, [allNews, appScope, competitor, keyword])

  const kpi = useMemo(() => {
    const total = filtered.length
    const counts: Record<string, number> = {}
    for (const n of filtered) {
      const text = `${n.title || ""} ${n.desc || ""}`.toLowerCase()
      for (const kw of ["partnership", "acquires", "funding"]) {
        if (text.includes(kw)) counts[kw] = (counts[kw] || 0) + 1
      }
    }
    return {
      total,
      partnership: counts.partnership || 0,
      acquires: counts.acquires || 0,
      funding: counts.funding || 0,
    }
  }, [filtered])

  return (
    <div>
      <PageHeader
        title="商业新闻"
        subtitle="Google News RSS · 命中 business 关键词的事件"
      />

      <KpiRow>
        <KpiCard label="新闻数" value={kpi.total} hint={`近 ${since}`} />
        <KpiCard label="partnership" value={kpi.partnership} hint="合作 / 联营" />
        <KpiCard label="acquires" value={kpi.acquires} hint="收并购" />
        <KpiCard label="funding" value={kpi.funding} hint="融资" />
      </KpiRow>

      <div className="space-y-2 mb-3">
        <AppScopeChip />
        <FilterChips label="时间" options={TIME_OPTIONS} value={since} onChange={(v) => setValue("since", v)} />
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
          label="关键词"
          options={[
            { value: "", label: "全部" },
            ...KEYWORDS.map((k) => ({ value: k, label: k })),
          ]}
          value={keyword}
          onChange={(v) => setValue("keyword", v)}
        />
      </div>

      {isLoading && <SkeletonTable rows={6} />}
      {isError && <EmptyState type="error" onRetry={() => refetch()} />}
      {!isLoading && !isError && filtered.length === 0 && (
        <EmptyState type="empty" hint="当前筛选下无新闻" />
      )}

      {filtered.length > 0 && (
        <div className="border border-border-soft rounded-md bg-card divide-y divide-border-soft">
          {filtered.map((n, i) => (
            <article
              key={`${n.link}-${i}`}
              className="px-3 py-2.5 hover:bg-muted/30 transition-colors duration-150"
            >
              <div className="flex items-baseline gap-2 mb-1">
                <span className="text-xs font-medium">{n.competitor}</span>
                <span className="text-2xs text-muted-foreground">{n.source}</span>
                {n.is_biz && (
                  <span className="text-2xs px-1 rounded bg-pill-amber-bg text-pill-amber-fg">⭐ biz</span>
                )}
                <span className="ml-auto text-2xs text-muted-foreground tabular-nums">
                  {n.pub_iso ? new Date(n.pub_iso).toLocaleDateString("zh-CN") : "—"}
                </span>
              </div>
              <a
                href={n.link}
                target="_blank"
                rel="noreferrer"
                className="text-sm font-medium hover:text-brand-700 inline-flex items-baseline gap-1"
              >
                {n.title}
                <ExternalLink className="w-3 h-3 shrink-0" />
              </a>
              {n.desc && (
                <p className="mt-1 text-xs text-muted-foreground line-clamp-2 leading-snug">
                  {n.desc}
                </p>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
