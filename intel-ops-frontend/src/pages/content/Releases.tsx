import { useMemo } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import AppScopeChip from "@/components/shared/AppScopeChip"
import EmptyState from "@/components/shared/EmptyState"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useAlerts } from "@/hooks/api/useAlerts"
import { useUrlFilters } from "@/hooks/useUrlFilters"
import { useFilterStore } from "@/stores/filterStore"
import FilterChips from "@/components/shared/FilterChips"
import { BASELINE_APP } from "@/types/domain"

export default function Releases() {
  const { value, setValue } = useUrlFilters({ since: "30d" })
  const since = value("since")
  const { appScope } = useFilterStore()

  const { data, isLoading, isError, refetch } = useAlerts({
    type: "release", since, limit: 200,
  })
  const filtered = useMemo(() => {
    return (data?.alerts || []).filter((a) => {
      if (appScope === "competitor" && a.app_name === BASELINE_APP) return false
      if (appScope === "baseline" && a.app_name !== BASELINE_APP) return false
      return true
    })
  }, [data, appScope])

  // 按 app 分组
  const byApp = useMemo(() => {
    const m = new Map<string, typeof filtered>()
    for (const a of filtered) {
      const k = a.app_name || "—"
      if (!m.has(k)) m.set(k, [])
      m.get(k)!.push(a)
    }
    return m
  }, [filtered])

  const kpi = {
    total: filtered.length,
    apps: byApp.size,
    locale: filtered.filter((a) =>
      JSON.stringify(a.metadata).match(/local|spanish|arabic|japanese|french/i)
    ).length,
    most: [...byApp.entries()].sort((a, b) => b[1].length - a[1].length)[0]?.[0] || "—",
  }

  return (
    <div>
      <PageHeader title="产品动态" subtitle="竞品版本发布节奏（来自 reviews.version 字段）" />

      <KpiRow>
        <KpiCard label="发版总数" value={kpi.total} hint={`近 ${since}`} />
        <KpiCard label="覆盖 app" value={kpi.apps} />
        <KpiCard label="本地化迹象" value={kpi.locale} hint="release notes 提及" />
        <KpiCard label="发版冠军" value={kpi.most} hint="活跃度 Top1" />
      </KpiRow>

      <div className="space-y-2 mb-3">
        <AppScopeChip />
        <FilterChips
          label="时间"
          options={[
            { value: "7d", label: "7d" },
            { value: "30d", label: "30d" },
            { value: "90d", label: "90d" },
          ]}
          value={since}
          onChange={(v) => setValue("since", v)}
        />
      </div>

      {isLoading && <SkeletonTable rows={6} />}
      {isError && <EmptyState type="error" onRetry={() => refetch()} />}
      {!isLoading && !isError && filtered.length === 0 && <EmptyState type="empty" />}

      {filtered.length > 0 && (
        <div className="space-y-3">
          {[...byApp.entries()]
            .sort((a, b) => b[1].length - a[1].length)
            .map(([app, list]) => (
              <section key={app} className="border border-border-soft rounded-md bg-card overflow-hidden">
                <header className="flex items-center justify-between px-3 h-9 bg-muted/30 border-b border-border-soft">
                  <span className="text-sm font-medium">
                    {app}
                    {app === BASELINE_APP && (
                      <span className="ml-2 text-2xs text-pill-blue-fg bg-pill-blue-bg px-1 rounded">baseline</span>
                    )}
                  </span>
                  <span className="text-2xs text-muted-foreground">{list.length} 次发版</span>
                </header>
                <div className="divide-y divide-border-soft">
                  {list.slice(0, 5).map((a) => {
                    const md = a.metadata as { version?: string; first_seen?: string; obs_count?: number }
                    return (
                      <div key={a.id} className="px-3 py-2 text-xs">
                        <div className="flex items-baseline gap-2">
                          <span className="font-mono font-medium">{md.version || "—"}</span>
                          <span className="text-2xs text-muted-foreground tabular-nums">
                            {md.first_seen ? new Date(md.first_seen).toLocaleDateString("zh-CN") : "—"}
                          </span>
                          {md.obs_count != null && (
                            <span className="text-2xs text-muted-foreground tabular-nums ml-auto">
                              {md.obs_count} 次观测
                            </span>
                          )}
                        </div>
                        {a.title && (
                          <div className="mt-0.5 text-muted-foreground line-clamp-2">{a.title}</div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </section>
            ))}
        </div>
      )}
    </div>
  )
}
