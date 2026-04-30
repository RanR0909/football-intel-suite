import DigestCard from "@/components/shared/DigestCard"
import { useAlerts } from "@/hooks/api/useAlerts"
import { Skeleton } from "@/components/shared/Skeleton"
import { cn } from "@/lib/utils"
import { ArrowUp, ArrowDown } from "lucide-react"

/** 总览·IAP 内购 — 24h 内 commercial 类 alerts（≤ 3 条）*/
export default function IapCard() {
  const { data, isLoading } = useAlerts({
    type: "commercial", since: "24h", limit: 5,
  })
  const top3 = (data?.alerts || []).slice(0, 3)
  const meta = data ? `24h 内 ${data.count} 条价格变动` : "—"

  return (
    <DigestCard title="IAP 内购" category="data" detailHref="/data/iap" meta={meta}>
      {isLoading && <Skeleton className="h-16" />}
      {!isLoading && top3.length === 0 && (
        <div className="text-xs text-muted-foreground py-3">24h 内无价格变动</div>
      )}
      {top3.length > 0 && (
        <ul className="space-y-1">
          {top3.map((a) => {
            const md = a.metadata as {
              iap_name?: string; old_price_usd?: number; new_price_usd?: number;
              change_pct?: number; regions_count?: number
            }
            const up = (md.change_pct ?? 0) > 0
            return (
              <li key={a.id} className="text-xs py-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium truncate flex-1">{a.app_name} · {md.iap_name}</span>
                  <span className={cn(
                    "inline-flex items-center gap-0.5 tabular-nums shrink-0",
                    up ? "text-semantic-danger" : "text-semantic-success"
                  )}>
                    {up ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />}
                    {Math.abs(md.change_pct ?? 0).toFixed(0)}%
                  </span>
                </div>
                <div className="text-2xs text-muted-foreground tabular-nums mt-0.5">
                  ${md.old_price_usd?.toFixed(2)} → ${md.new_price_usd?.toFixed(2)}
                  {md.regions_count != null && ` · 影响 ${md.regions_count} 区`}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </DigestCard>
  )
}
