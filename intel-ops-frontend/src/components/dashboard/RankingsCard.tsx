import DigestCard from "@/components/shared/DigestCard"
import { useAlerts } from "@/hooks/api/useAlerts"
import { Skeleton } from "@/components/shared/Skeleton"
import { ArrowUp, ArrowDown } from "lucide-react"
import { cn } from "@/lib/utils"
import { REGION_LABELS, type Region } from "@/types/domain"

/**
 * 总览·排名异动 — 取最近 24h 的 ranking alerts
 * 显示 4 条最关键（severity high → mid → low）
 */
export default function RankingsCard() {
  const { data, isLoading } = useAlerts({
    type: "ranking", since: "24h", limit: 20,
  })
  const top4 = (data?.alerts || []).slice(0, 4)
  const meta = data ? `24h 内 ${data.count} 条异动` : "—"

  return (
    <DigestCard title="排名异动" category="data" detailHref="/data/rankings" meta={meta}>
      {isLoading && <Skeleton className="h-20" />}
      {!isLoading && top4.length === 0 && (
        <div className="text-xs text-muted-foreground py-3">24h 内无显著异动</div>
      )}
      {top4.length > 0 && (
        <ul className="space-y-1">
          {top4.map((a) => {
            const md = a.metadata as { region?: string; old_rank?: number; new_rank?: number; change?: number }
            const region = md.region || ""
            const change = md.change ?? 0
            const up = change > 0
            return (
              <li key={a.id} className="flex items-center gap-2 text-xs py-1">
                <span className="font-medium truncate flex-1">{a.app_name}</span>
                <span className="text-2xs text-muted-foreground tabular-nums">
                  {REGION_LABELS[region as Region] || region.toUpperCase()}
                </span>
                <span className="tabular-nums text-muted-foreground">
                  #{md.old_rank} → #{md.new_rank}
                </span>
                <span className={cn(
                  "inline-flex items-center gap-0.5 tabular-nums w-12 justify-end",
                  up ? "text-semantic-success" : "text-semantic-danger"
                )}>
                  {up ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />}
                  {Math.abs(change)}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </DigestCard>
  )
}
