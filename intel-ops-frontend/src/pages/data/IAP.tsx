import { useMemo } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import FilterChips from "@/components/shared/FilterChips"
import EmptyState from "@/components/shared/EmptyState"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useIap } from "@/hooks/api/useIap"
import { useUrlFilters } from "@/hooks/useUrlFilters"
import { COMPETITORS, REGION_LABELS, type Region } from "@/types/domain"

export default function IAP() {
  const { value, setValue } = useUrlFilters({ competitor: "" })
  const competitor = value("competitor")

  const { data, isLoading, isError, refetch } = useIap({
    competitor, limit: 1000,
  })
  // 按 spec：IAP 页只展示 9 竞品，AF 不渲染
  const all = (data?.iap_items || []).filter((it) => COMPETITORS.includes(it.competitor as typeof COMPETITORS[number]))

  // 按 (competitor, name) 分组合并 region 价格
  const grouped = useMemo(() => {
    const m = new Map<string, Map<string, typeof all>>()
    for (const it of all) {
      if (!m.has(it.competitor)) m.set(it.competitor, new Map())
      const inner = m.get(it.competitor)!
      if (!inner.has(it.name)) inner.set(it.name, [])
      inner.get(it.name)!.push(it)
    }
    return m
  }, [all])

  // KPI
  const kpi = useMemo(() => {
    let totalIap = 0
    for (const inner of grouped.values()) totalIap += inner.size
    return {
      apps: grouped.size,
      iaps: totalIap,
      regions: new Set(all.map((it) => it.region_code)).size,
      records: all.length,
    }
  }, [grouped, all])

  return (
    <div>
      <PageHeader
        title="IAP 内购"
        subtitle="9 竞品的 IAP 商品配置（按 spec 不展示 AllFootball）"
      />

      <KpiRow>
        <KpiCard label="覆盖竞品" value={kpi.apps} />
        <KpiCard label="IAP 总数" value={kpi.iaps} hint="去重后" />
        <KpiCard label="覆盖区域" value={kpi.regions} />
        <KpiCard label="价格记录" value={kpi.records} hint="原始行数" />
      </KpiRow>

      <div className="mb-3">
        <FilterChips
          label="竞品"
          options={[
            { value: "", label: "全部" },
            ...COMPETITORS.map((c) => ({ value: c, label: c })),
          ]}
          value={competitor}
          onChange={(v) => setValue("competitor", v)}
        />
      </div>

      {isLoading && <SkeletonTable rows={8} />}
      {isError && <EmptyState type="error" onRetry={() => refetch()} />}
      {!isLoading && !isError && all.length === 0 && (
        <EmptyState type="empty" hint="9 竞品基本免费 / 暂未抓到" />
      )}

      {grouped.size > 0 && (
        <div className="space-y-3">
          {[...grouped.entries()].map(([app, items]) => (
            <section key={app} className="border border-border-soft rounded-md bg-card">
              <header className="flex items-center justify-between px-3 h-9 bg-muted/30 border-b border-border-soft">
                <span className="text-sm font-medium">{app}</span>
                <span className="text-2xs text-muted-foreground">{items.size} 个 IAP</span>
              </header>
              <table className="w-full text-xs">
                <thead className="text-2xs uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="text-left px-3 py-1.5">名称</th>
                    <th className="text-left px-3 py-1.5">类型</th>
                    <th className="text-left px-3 py-1.5">区域 × 价格</th>
                    <th className="text-right px-3 py-1.5">最近抓取</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-soft">
                  {[...items.entries()].map(([name, regions]) => {
                    const sample = regions[0]
                    const latest = regions.reduce<typeof regions[number] | null>(
                      (acc, r) => (!acc || r.fetched_at > acc.fetched_at ? r : acc),
                      null
                    )
                    return (
                      <tr key={name} className="hover:bg-muted/30">
                        <td className="px-3 py-2 align-top max-w-xs">
                          <div className="truncate font-medium">{name}</div>
                        </td>
                        <td className="px-3 py-2 align-top text-muted-foreground">
                          {sample.category || "—"}
                        </td>
                        <td className="px-3 py-2 align-top">
                          <div className="flex flex-wrap gap-1">
                            {regions.slice(0, 12).map((r) => (
                              <span key={r.id} className="inline-flex items-center gap-1 px-1.5 h-5 rounded bg-muted/40 text-2xs font-mono">
                                <span className="uppercase text-muted-foreground"
                                  title={REGION_LABELS[r.region_code as Region] || r.region_code}>
                                  {r.region_code}
                                </span>
                                <span className="tabular-nums">{r.price || "—"}</span>
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="px-3 py-2 align-top text-right text-2xs text-muted-foreground tabular-nums">
                          {latest ? new Date(latest.fetched_at).toLocaleDateString("zh-CN") : "—"}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
