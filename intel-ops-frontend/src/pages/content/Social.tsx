import { useMemo } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import FilterChips from "@/components/shared/FilterChips"
import AppScopeChip from "@/components/shared/AppScopeChip"
import EmptyState from "@/components/shared/EmptyState"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useCommunity } from "@/hooks/api/useCommunity"
import { useUrlFilters } from "@/hooks/useUrlFilters"
import { useFilterStore } from "@/stores/filterStore"
import { ArrowUp, MessageCircle, ExternalLink } from "lucide-react"
import { BASELINE_APP, COMPETITORS } from "@/types/domain"

const SOURCE_OPTIONS = [
  { value: "", label: "全部" },
  { value: "reddit", label: "Reddit" },
  { value: "twitter", label: "Twitter" },
]

export default function Social() {
  const { value, setValue } = useUrlFilters({ source: "", competitor: "" })
  const source = value("source") as "reddit" | "twitter" | ""
  const competitor = value("competitor")
  const { appScope } = useFilterStore()

  const { data, isLoading, isError, refetch } = useCommunity({
    source: source || undefined, competitor, limit: 200,
  })
  const all = data?.posts || []
  const filtered = useMemo(() => {
    return all.filter((p) => {
      if (appScope === "competitor" && p.competitor === BASELINE_APP) return false
      if (appScope === "baseline" && p.competitor !== BASELINE_APP) return false
      return true
    })
  }, [all, appScope])

  const kpi = useMemo(() => ({
    total: filtered.length,
    reddit: filtered.filter((p) => p.source === "reddit").length,
    twitter: filtered.filter((p) => p.source === "twitter").length,
    hot: filtered.filter((p) => (p.score || 0) >= 100).length,
  }), [filtered])

  return (
    <div>
      <PageHeader title="社媒评论" subtitle="Reddit + Twitter 帖子（按热度排序）" />

      <KpiRow>
        <KpiCard label="总帖子数" value={kpi.total} />
        <KpiCard label="Reddit" value={kpi.reddit} />
        <KpiCard label="Twitter" value={kpi.twitter} hint="待 fapi.uk 付费 token" />
        <KpiCard label="高热（≥100）" value={kpi.hot} />
      </KpiRow>

      <div className="space-y-2 mb-3">
        <AppScopeChip />
        <FilterChips label="来源" options={SOURCE_OPTIONS} value={source} onChange={(v) => setValue("source", v)} />
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
      {!isLoading && !isError && filtered.length === 0 && <EmptyState type="empty" />}

      {filtered.length > 0 && (
        <div className="border border-border-soft rounded-md bg-card divide-y divide-border-soft">
          {filtered.map((p) => (
            <article key={p.id} className="px-3 py-3 hover:bg-muted/30 transition-colors duration-150">
              <div className="flex items-baseline gap-2 mb-1 flex-wrap">
                <span className="text-xs font-medium">{p.competitor}</span>
                <span className="text-2xs px-1 rounded font-mono bg-muted/40 text-muted-foreground uppercase">
                  {p.source}
                </span>
                {p.subreddit && (
                  <span className="text-2xs text-muted-foreground font-mono">r/{p.subreddit}</span>
                )}
                <span className="ml-auto inline-flex items-center gap-3 text-2xs text-muted-foreground tabular-nums">
                  {p.score != null && (
                    <span className="inline-flex items-center gap-0.5"><ArrowUp className="w-3 h-3" />{p.score}</span>
                  )}
                  {p.num_comments != null && (
                    <span className="inline-flex items-center gap-0.5"><MessageCircle className="w-3 h-3" />{p.num_comments}</span>
                  )}
                  {p.created_utc && (
                    <span>{new Date(p.created_utc).toLocaleDateString("zh-CN")}</span>
                  )}
                </span>
              </div>
              <a
                href={p.url || "#"}
                target="_blank"
                rel="noreferrer"
                className="text-sm font-medium hover:text-brand-700 inline-flex items-baseline gap-1"
              >
                {p.title || "(无标题)"}
                <ExternalLink className="w-3 h-3 shrink-0" />
              </a>
              {p.selftext && (
                <p className="mt-1 text-xs text-muted-foreground line-clamp-3 leading-snug">
                  {p.selftext}
                </p>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
