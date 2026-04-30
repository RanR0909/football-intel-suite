import { useStatus } from "@/hooks/api/useDashboardData"
import { cn } from "@/lib/utils"
import { CheckCircle2, XCircle, Clock, MinusCircle } from "lucide-react"

const SOURCES = [
  "appstore_rank", "androidrank", "comment_fetch", "reddit",
  "twitter", "iap_pricing", "google_news", "strategy_monitor",
  "appmagic", "fb_adlib", "sensor_tower", "similarweb_traffic",
  "ai_pipeline",
]

type Status = "ok" | "fail" | "pending" | "skip" | "unknown"

const STATUS_STYLE: Record<Status, { icon: React.ElementType; color: string }> = {
  ok:      { icon: CheckCircle2, color: "text-semantic-success" },
  fail:    { icon: XCircle,      color: "text-semantic-danger" },
  pending: { icon: Clock,        color: "text-semantic-warning" },
  skip:    { icon: MinusCircle,  color: "text-muted-foreground" },
  unknown: { icon: MinusCircle,  color: "text-muted-foreground" },
}

export default function SyncStatusBar() {
  const { data, isLoading } = useStatus()

  const sources = data?.sources || {}
  const failed = Object.values(data?.failed_ai_jobs || {}).reduce((a: number, b) => a + (b as number), 0)
  const queueSize = data?.retry_queue_size ?? 0

  const overall: Status = (() => {
    if (isLoading) return "pending"
    const items = SOURCES.map((k) => (sources[k]?.status as Status) || "unknown")
    if (items.some((s) => s === "fail")) return "fail"
    if (items.some((s) => s === "pending")) return "pending"
    if (items.every((s) => s === "ok" || s === "skip")) return "ok"
    return "unknown"
  })()

  const overallStyle = STATUS_STYLE[overall]
  const OverallIcon = overallStyle.icon

  return (
    <div className="flex items-center gap-3 px-3 py-2 border border-border-soft rounded-md bg-card text-xs">
      <div className={cn("flex items-center gap-1.5 shrink-0", overallStyle.color)}>
        <OverallIcon className="w-3.5 h-3.5" />
        <span className="font-medium">
          {overall === "ok" && "同步 OK"}
          {overall === "fail" && "有失败"}
          {overall === "pending" && "重试中"}
          {overall === "unknown" && "未知"}
        </span>
      </div>
      <div className="text-muted-foreground shrink-0">
        retry queue: {queueSize} · failed AI: {failed}
      </div>
      <div className="flex-1 flex flex-wrap gap-1 min-w-0">
        {SOURCES.map((src) => {
          const s = (sources[src]?.status as Status) || "unknown"
          const style = STATUS_STYLE[s]
          return (
            <div
              key={src}
              className={cn(
                "inline-flex items-center gap-1 px-1.5 h-5 rounded bg-muted/40 text-2xs",
                style.color
              )}
              title={`${src}: ${s}${sources[src]?.last_success ? ` (${sources[src].last_success})` : ""}`}
            >
              <style.icon className="w-3 h-3" />
              <span className="font-mono">{src}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
