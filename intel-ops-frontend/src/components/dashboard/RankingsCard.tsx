import DigestCard from "@/components/shared/DigestCard"
import { useAlerts } from "@/hooks/api/useAlerts"
import { Skeleton } from "@/components/shared/Skeleton"
import { ArrowUp, ArrowDown } from "lucide-react"
import { cn } from "@/lib/utils"
import { REGION_LABELS, type Region } from "@/types/domain"

/** 总览·排名异动 — 7d 内 ranking alerts，无数据则折叠 */
export default function RankingsCard() {
  const { data, isLoading } = useAlerts({
    type: "ranking", since: "7d", limit: 20,
  })
  const top = (data?.alerts || []).slice(0, 3)

  if (isLoading) {
    return (
      <DigestCard title="排名异动" detailHref="/data/rankings">
        <Skeleton className="h-16" />
      </DigestCard>
    )
  }

  if (top.length === 0) {
    return (
      <DigestCard
        title="排名异动"
        detailHref="/data/rankings"
        collapsed
        emptyMsg="7d 无显著异动"
      />
    )
  }

  return (
    <DigestCard title="排名异动" detailHref="/data/rankings">
      <ul className="text-xs">
        {top.map((a) => {
          const md = a.metadata as { region?: string; old_rank?: number; new_rank?: number; change?: number }
          const region = md.region || ""
          const change = md.change ?? 0
          const up = change > 0
          return (
            <li key={a.id} className="flex items-center gap-2 py-1 border-b border-border-soft last:border-0">
              <span className="font-medium truncate flex-1">{a.app_name}</span>
              <span className="text-2xs text-muted-foreground tabular-nums">
                {REGION_LABELS[region as Region] || region.toUpperCase()}
              </span>
              <span className={cn(
                "inline-flex items-center gap-0.5 tabular-nums font-mono",
                up ? "text-semantic-success" : "text-semantic-danger"
              )}>
                {up ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />}
                {Math.abs(change)}
              </span>
            </li>
          )
        })}
      </ul>
    </DigestCard>
  )
}
