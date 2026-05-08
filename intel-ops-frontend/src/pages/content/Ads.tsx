/** 广告投放页 — 数据量小（< 50 条）时的简化版
 *
 * v1 (KPI + 维度 toggle + 子聚合 tab) 是为几百条创意设计的；目前 fb_adlib 走 page_id
 * 精确模式后总命中只有 11 条，KPI 卡 / 卖点策略 / 区域策略 / 竞品创意对比 都没数据。
 * 砍到一张表 + 一行 per-competitor 统计 + 国家/竞品筛选。等 AI 分类跑出来或数据涨到
 * 50+ 再考虑恢复维度 tab。
 */
import { useMemo } from "react"
import PageHeader from "@/components/shared/PageHeader"
import FilterChips from "@/components/shared/FilterChips"
import EmptyState from "@/components/shared/EmptyState"
import Pill from "@/components/shared/Pill"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useAds } from "@/hooks/api/useAds"
import { useUrlFilters } from "@/hooks/useUrlFilters"
import {
  COMPETITORS, REGION_LABELS, SELLING_POINT_LABELS,
} from "@/types/domain"

const COUNTRY_OPTIONS = [
  { value: "", label: "全部" },
  { value: "us", label: REGION_LABELS.us },
  { value: "gb", label: REGION_LABELS.gb },
  { value: "br", label: REGION_LABELS.br },
  { value: "de", label: REGION_LABELS.de },
  { value: "jp", label: REGION_LABELS.jp },
]

function fmtDate(s: string | null): string {
  if (!s) return "—"
  const d = new Date(s)
  if (!Number.isFinite(d.valueOf())) return s
  return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")}`
}

function daysRunning(s: string | null): string {
  if (!s) return "—"
  const d = new Date(s)
  if (!Number.isFinite(d.valueOf())) return "—"
  const days = Math.max(0, Math.floor((Date.now() - d.valueOf()) / 86400_000))
  return `${days}d`
}

export default function Ads() {
  const { value, setValue } = useUrlFilters({ country: "", competitor: "" })
  const country = value("country")
  const competitor = value("competitor")

  // 拉所有（11 条不需要分页），客户端按 country/competitor 过滤
  const { data: rawAds, isLoading, isError, refetch } = useAds({ limit: 500 })
  const allAds = useMemo(() => rawAds?.ads || [], [rawAds])

  // per-competitor 命中数（用于头部统计行 + 竞品筛选只显示有数据的）
  const compStats = useMemo(() => {
    const tally: Record<string, number> = {}
    for (const c of COMPETITORS) tally[c] = 0
    for (const a of allAds) tally[a.competitor] = (tally[a.competitor] || 0) + 1
    return COMPETITORS.map((c) => ({ name: c, n: tally[c] || 0 }))
                     .sort((a, b) => b.n - a.n)
  }, [allAds])

  const competitorsWithAds = useMemo(
    () => compStats.filter((s) => s.n > 0).map((s) => s.name),
    [compStats]
  )

  // 应用筛选
  const filteredAds = useMemo(() => {
    return allAds.filter((a) => {
      if (country && a.region !== country) return false
      if (competitor && a.competitor !== competitor) return false
      return true
    })
  }, [allAds, country, competitor])

  if (isLoading) return <div><PageHeader title="广告投放" /><SkeletonTable rows={5} /></div>
  if (isError) return <div><PageHeader title="广告投放" /><EmptyState type="error" onRetry={() => refetch()} /></div>

  return (
    <div>
      <PageHeader
        title="广告投放"
        subtitle="Meta 广告库 · 按 fb_page_id 精确匹配（仅竞品官方 Page 投放的广告）"
      />

      {/* per-competitor 命中数（一行紧凑） */}
      <div className="text-xs mb-3 leading-relaxed">
        {compStats.map((s, i) => (
          <span key={s.name}>
            {i > 0 && <span className="text-border-soft mx-2">·</span>}
            <span className={s.n === 0 ? "text-muted-foreground/60" : "font-medium"}>
              {s.name} <span className="tabular-nums">{s.n}</span>
            </span>
          </span>
        ))}
      </div>

      {/* 筛选 */}
      <div className="space-y-2 mb-3">
        <FilterChips
          label="国家"
          options={COUNTRY_OPTIONS}
          value={country}
          onChange={(v) => setValue("country", v)}
        />
        <FilterChips
          label="竞品"
          options={[
            { value: "", label: "全部" },
            ...competitorsWithAds.map((c) => ({ value: c, label: c })),
          ]}
          value={competitor}
          onChange={(v) => setValue("competitor", v)}
        />
      </div>

      {/* 表格 */}
      {filteredAds.length === 0 ? (
        <EmptyState type="empty" hint="所选条件下没有广告" />
      ) : (
        <div className="border border-border-soft rounded-md bg-card overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-muted/30">
              <tr className="text-2xs uppercase tracking-wider text-muted-foreground">
                <th className="text-left  px-3 h-8 w-32">竞品</th>
                <th className="text-left  px-3 h-8 w-14">国家</th>
                <th className="text-left  px-3 h-8 w-24">起投日</th>
                <th className="text-right px-3 h-8 w-16">已投</th>
                <th className="text-left  px-3 h-8">原文</th>
                <th className="text-right px-3 h-8 w-20"></th>
              </tr>
            </thead>
            <tbody>
              {filteredAds.map((a) => (
                <tr key={a.id} className="border-t border-border-soft hover:bg-muted/30">
                  <td className="px-3 py-2 font-medium">{a.competitor}</td>
                  <td className="px-3 py-2">
                    <Pill variant="gray">{a.region.toUpperCase()}</Pill>
                  </td>
                  <td className="px-3 py-2 font-mono tabular-nums text-muted-foreground">
                    {fmtDate(a.start_date)}
                  </td>
                  <td className="px-3 py-2 font-mono tabular-nums text-right">
                    {daysRunning(a.start_date)}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1.5">
                      {(a.selling_points || []).slice(0, 2).map((sp) => (
                        <Pill key={sp} variant="amber">{SELLING_POINT_LABELS[sp]}</Pill>
                      ))}
                      <span className="text-muted-foreground line-clamp-1 flex-1" title={a.body_text || ""}>
                        {a.body_text || "(无文案)"}
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right">
                    {a.ad_id && (
                      <a
                        href={`https://www.facebook.com/ads/library/?id=${a.ad_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-2xs text-semantic-info hover:underline tabular-nums"
                        title={`Meta Ad Library · ID ${a.ad_id}`}
                      >
                        原投放 ↗
                      </a>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
