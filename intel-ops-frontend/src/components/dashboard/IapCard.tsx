import DigestCard from "@/components/shared/DigestCard"
import { useAlerts } from "@/hooks/api/useAlerts"
import { Skeleton } from "@/components/shared/Skeleton"
import { cn } from "@/lib/utils"
import { ArrowUp, ArrowDown } from "lucide-react"

/** 总览·IAP 内购 — 24h commercial alerts；无价格变动时折叠 */
export default function IapCard() {
  const { data, isLoading } = useAlerts({
    type: "commercial", since: "24h", limit: 5,
  })
  const top = (data?.alerts || []).slice(0, 3)

  if (isLoading) {
    return (
      <DigestCard title="IAP 内购" detailHref="/data/iap">
        <Skeleton className="h-16" />
      </DigestCard>
    )
  }

  if (top.length === 0) {
    return (
      <DigestCard
        title="IAP 内购"
        detailHref="/data/iap"
        collapsed
        emptyMsg="24h 无价格变动"
      />
    )
  }

  return (
    <DigestCard title="IAP 内购" detailHref="/data/iap">
      <ul className="text-xs">
        {top.map((a) => {
          const md = a.metadata as {
            iap_name?: string; old_price_usd?: number; new_price_usd?: number;
            change_pct?: number; regions_count?: number
          }
          const up = (md.change_pct ?? 0) > 0
          return (
            <li key={a.id} className="py-1 border-b border-border-soft last:border-0">
              <div className="flex items-center gap-2">
                <span className="font-medium truncate flex-1">{a.app_name}</span>
                <span className={cn(
                  "inline-flex items-center gap-0.5 tabular-nums font-mono shrink-0",
                  up ? "text-semantic-danger" : "text-semantic-success"
                )}>
                  {up ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />}
                  {Math.abs(md.change_pct ?? 0).toFixed(0)}%
                </span>
              </div>
              <div className="text-2xs text-muted-foreground tabular-nums truncate">
                {md.iap_name} · ${md.old_price_usd?.toFixed(2)} → ${md.new_price_usd?.toFixed(2)}
              </div>
            </li>
          )
        })}
      </ul>
    </DigestCard>
  )
}
