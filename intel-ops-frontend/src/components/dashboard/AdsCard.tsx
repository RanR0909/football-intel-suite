import DigestCard from "@/components/shared/DigestCard"
import Pill from "@/components/shared/Pill"
import { useAds } from "@/hooks/api/useAds"
import { Skeleton } from "@/components/shared/Skeleton"
import { SELLING_POINT_LABELS } from "@/types/domain"

/** 总览·广告投放（窄列版） — 2 个竞品最新文案 */
export default function AdsCard() {
  const { data, isLoading } = useAds({ limit: 100 })
  const all = data?.ads || []

  const byApp = new Map<string, typeof all[number]>()
  const sorted = [...all].sort((a, b) => {
    const sa = (a.selling_points || []).length > 0 ? 1 : 0
    const sb = (b.selling_points || []).length > 0 ? 1 : 0
    if (sa !== sb) return sb - sa
    return (b.fetched_at || "").localeCompare(a.fetched_at || "")
  })
  for (const ad of sorted) {
    if (!byApp.has(ad.competitor) && ad.body_text) byApp.set(ad.competitor, ad)
    if (byApp.size >= 2) break
  }
  const top = [...byApp.values()]

  const compCount = new Map<string, number>()
  for (const ad of all) compCount.set(ad.competitor, (compCount.get(ad.competitor) || 0) + 1)

  return (
    <DigestCard title="广告投放" detailHref="/content/ads">
      {isLoading && <Skeleton className="h-16" />}
      {!isLoading && top.length === 0 && (
        <div className="text-xs text-muted-foreground py-2">暂无广告创意</div>
      )}
      {top.length > 0 && (
        <ul className="space-y-2">
          {top.map((ad) => {
            const sps = (ad.selling_points || []).slice(0, 1)
            return (
              <li key={ad.id} className="text-xs">
                <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
                  <span className="font-medium">{ad.competitor}</span>
                  <Pill variant="gray">{ad.region.toUpperCase()}</Pill>
                  {sps.map((sp) => (
                    <Pill key={sp} variant="amber">{SELLING_POINT_LABELS[sp]}</Pill>
                  ))}
                  <span className="ml-auto text-2xs text-muted-foreground font-mono tabular-nums">
                    活跃 {compCount.get(ad.competitor) || 0}
                  </span>
                </div>
                <p className="text-muted-foreground line-clamp-2 leading-snug pl-2 border-l-2 border-border-soft">
                  {ad.body_text}
                </p>
              </li>
            )
          })}
        </ul>
      )}
    </DigestCard>
  )
}
