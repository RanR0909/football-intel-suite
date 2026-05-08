import DigestCard from "@/components/shared/DigestCard"
import Pill from "@/components/shared/Pill"
import { useAds } from "@/hooks/api/useAds"
import { Skeleton } from "@/components/shared/Skeleton"
import { SELLING_POINT_LABELS } from "@/types/domain"

/** 总览·广告投放（占双列） — 4 个竞品文案对比，2x2 排列 */
export default function AdsCard() {
  const { data, isLoading } = useAds({ limit: 100 })
  const all = data?.ads || []

  // 按 competitor 分桶取最新一条有文案的；优先有 selling_points 的
  const byApp = new Map<string, typeof all[number]>()
  const sorted = [...all].sort((a, b) => {
    const sa = (a.selling_points || []).length > 0 ? 1 : 0
    const sb = (b.selling_points || []).length > 0 ? 1 : 0
    if (sa !== sb) return sb - sa
    return (b.fetched_at || "").localeCompare(a.fetched_at || "")
  })
  for (const ad of sorted) {
    if (!byApp.has(ad.competitor) && ad.body_text) byApp.set(ad.competitor, ad)
    if (byApp.size >= 4) break
  }
  const top4 = [...byApp.values()]

  // 每个竞品的活跃创意计数
  const compCount = new Map<string, number>()
  for (const ad of all) compCount.set(ad.competitor, (compCount.get(ad.competitor) || 0) + 1)

  return (
    <DigestCard title="广告投放" detailHref="/content/ads" className="col-span-2">
      {isLoading && <Skeleton className="h-24" />}
      {!isLoading && top4.length === 0 && (
        <div className="text-xs text-muted-foreground py-2">暂无广告创意</div>
      )}
      {top4.length > 0 && (
        <div className="grid grid-cols-2 gap-x-6 gap-y-3">
          {top4.map((ad) => {
            const sps = (ad.selling_points || []).slice(0, 2)
            return (
              <div key={ad.id} className="text-xs">
                <div className="flex items-center gap-1.5 mb-1 flex-wrap">
                  <span className="font-medium">{ad.competitor}</span>
                  <Pill variant="gray">{ad.region.toUpperCase()}</Pill>
                  <span className="ml-auto text-2xs text-muted-foreground font-mono tabular-nums">
                    活跃 {compCount.get(ad.competitor) || 0}
                  </span>
                </div>
                {sps.length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-1">
                    {sps.map((sp) => (
                      <Pill key={sp} variant="amber">{SELLING_POINT_LABELS[sp]}</Pill>
                    ))}
                  </div>
                )}
                <p className="text-muted-foreground line-clamp-2 leading-snug pl-2 border-l-2 border-border-soft">
                  {ad.body_text}
                </p>
              </div>
            )
          })}
        </div>
      )}
    </DigestCard>
  )
}
