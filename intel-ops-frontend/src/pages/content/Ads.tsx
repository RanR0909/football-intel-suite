import { useMemo } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import FilterChips from "@/components/shared/FilterChips"
import AppScopeChip from "@/components/shared/AppScopeChip"
import EmptyState from "@/components/shared/EmptyState"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useAds } from "@/hooks/api/useAds"
import { useUrlFilters } from "@/hooks/useUrlFilters"
import { useFilterStore } from "@/stores/filterStore"
import { BASELINE_APP, COMPETITORS, REGION_LABELS, type Region } from "@/types/domain"

const COUNTRY_OPTIONS = [
  { value: "", label: "全部" },
  { value: "us", label: REGION_LABELS.us },
  { value: "gb", label: REGION_LABELS.gb },
  { value: "br", label: REGION_LABELS.br },
  { value: "mx", label: REGION_LABELS.mx },
  { value: "ng", label: REGION_LABELS.ng },
]

export default function Ads() {
  const { value, setValue } = useUrlFilters({ country: "", competitor: "" })
  const country = value("country")
  const competitor = value("competitor")
  const { appScope } = useFilterStore()

  const { data, isLoading, isError, refetch } = useAds({
    country, competitor, limit: 500,
  })
  const filtered = useMemo(() => {
    return (data?.ads || []).filter((a) => {
      if (appScope === "competitor" && a.competitor === BASELINE_APP) return false
      if (appScope === "baseline" && a.competitor !== BASELINE_APP) return false
      return true
    })
  }, [data, appScope])

  // 按 (competitor, region) 分桶
  const matrix = useMemo(() => {
    const m = new Map<string, Map<string, typeof filtered>>()
    for (const ad of filtered) {
      if (!m.has(ad.competitor)) m.set(ad.competitor, new Map())
      const inner = m.get(ad.competitor)!
      if (!inner.has(ad.region)) inner.set(ad.region, [])
      inner.get(ad.region)!.push(ad)
    }
    return m
  }, [filtered])

  const totalActive = filtered.length
  const topCompetitor = [...matrix.entries()]
    .map(([c, regions]) => ({
      c, n: [...regions.values()].reduce((sum, arr) => sum + arr.length, 0),
    }))
    .sort((a, b) => b.n - a.n)[0]?.c || "—"
  const topRegion = useMemo(() => {
    const tally: Record<string, number> = {}
    for (const ad of filtered) tally[ad.region] = (tally[ad.region] || 0) + 1
    const top = Object.entries(tally).sort((a, b) => b[1] - a[1])[0]
    return top ? `${REGION_LABELS[top[0] as Region] || top[0].toUpperCase()} (${top[1]})` : "—"
  }, [filtered])

  return (
    <div>
      <PageHeader title="广告投放" subtitle="Meta 广告库 · 竞品 × 国家矩阵" />

      <KpiRow>
        <KpiCard label="活跃创意" value={totalActive} hint="所有 region" />
        <KpiCard label="覆盖竞品" value={matrix.size} />
        <KpiCard label="投放 Top1 竞品" value={topCompetitor} />
        <KpiCard label="投放 Top1 国家" value={topRegion} />
      </KpiRow>

      <div className="space-y-2 mb-3">
        <AppScopeChip />
        <FilterChips label="国家" options={COUNTRY_OPTIONS} value={country} onChange={(v) => setValue("country", v)} />
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
        <div className="space-y-2">
          {[...matrix.entries()]
            .sort((a, b) => {
              const ca = [...a[1].values()].reduce((s, x) => s + x.length, 0)
              const cb = [...b[1].values()].reduce((s, x) => s + x.length, 0)
              return cb - ca
            })
            .map(([app, regions]) => {
              const total = [...regions.values()].reduce((s, x) => s + x.length, 0)
              return (
                <section key={app} className="border border-border-soft rounded-md bg-card">
                  <header className="flex items-center justify-between px-3 h-9 bg-muted/30 border-b border-border-soft">
                    <span className="text-sm font-medium">
                      {app}
                      {app === BASELINE_APP && (
                        <span className="ml-2 text-2xs text-pill-blue-fg bg-pill-blue-bg px-1 rounded">baseline</span>
                      )}
                    </span>
                    <span className="text-2xs text-muted-foreground">
                      {total} 创意 · {regions.size} 国
                    </span>
                  </header>
                  <div className="grid grid-cols-1 md:grid-cols-2 divide-x divide-border-soft">
                    {[...regions.entries()].map(([region, ads]) => (
                      <div key={region} className="p-3 space-y-2">
                        <div className="text-2xs uppercase font-mono text-muted-foreground">
                          {REGION_LABELS[region as Region] || region.toUpperCase()} · {ads.length}
                        </div>
                        {ads.slice(0, 3).map((ad) => (
                          <div key={ad.id} className="text-xs text-muted-foreground line-clamp-3 leading-snug border-l-2 border-border pl-2">
                            {ad.body_text || "(无文案)"}
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                </section>
              )
            })}
        </div>
      )}
    </div>
  )
}
