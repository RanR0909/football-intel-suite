import DigestCard from "@/components/shared/DigestCard"
import { useAds } from "@/hooks/api/useAds"
import { Skeleton } from "@/components/shared/Skeleton"

/** 总览·广告投放（占双列） — 4 大竞品广告文案对比 */
export default function AdsCard() {
  const { data, isLoading } = useAds({ limit: 50 })
  const all = data?.ads || []

  // 按 competitor 分桶，每个 competitor 取一条最新文案
  const byApp = new Map<string, typeof all[number]>()
  for (const ad of all) {
    if (!byApp.has(ad.competitor) && ad.body_text) {
      byApp.set(ad.competitor, ad)
    }
    if (byApp.size >= 4) break
  }
  const top4 = [...byApp.values()]
  const meta = data ? `${data.count} 条活跃广告` : "—"

  return (
    <DigestCard title="广告投放" category="content" detailHref="/content/ads" meta={meta} className="col-span-2">
      {isLoading && <Skeleton className="h-24" />}
      {!isLoading && top4.length === 0 && (
        <div className="text-xs text-muted-foreground py-3">暂无广告创意</div>
      )}
      {top4.length > 0 && (
        <div className="grid grid-cols-2 gap-x-4 gap-y-2">
          {top4.map((ad) => (
            <div key={ad.id} className="text-xs">
              <div className="flex items-center gap-1.5 mb-1">
                <span className="font-medium">{ad.competitor}</span>
                <span className="text-2xs text-muted-foreground font-mono uppercase">
                  {ad.region}
                </span>
              </div>
              <p className="text-muted-foreground line-clamp-3 leading-snug">
                {ad.body_text}
              </p>
            </div>
          ))}
        </div>
      )}
    </DigestCard>
  )
}
