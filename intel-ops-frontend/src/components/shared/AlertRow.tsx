import { Link } from "react-router-dom"
import { Check, ExternalLink } from "lucide-react"
import SeverityBar from "./SeverityBar"
import { cn } from "@/lib/utils"
import { ALERT_TYPE_LABELS } from "@/types/domain"
import type { Alert } from "@/types/api"

interface AlertRowProps {
  alert: Alert
  onAck?: (id: number) => void
  className?: string
}

/** 把 alert 跳到对应子页（带预筛选参数）*/
function buildDetailHref(a: Alert): string {
  const app = a.app_name || ""
  switch (a.alert_type) {
    case "ranking":     return `/data/rankings?competitor=${encodeURIComponent(app)}`
    case "commercial":  return `/data/iap?competitor=${encodeURIComponent(app)}`
    case "news":        return `/content/news?competitor=${encodeURIComponent(app)}`
    case "release":     return `/content/releases?competitor=${encodeURIComponent(app)}`
    case "rating":      return `/content/gp-reviews?competitor=${encodeURIComponent(app)}`
    case "churn":       return `/content/gp-reviews?competitor=${encodeURIComponent(app)}&label=churn_signal`
    case "ads":         return `/content/ads?competitor=${encodeURIComponent(app)}`
    default:            return "/alerts"
  }
}

function formatTime(iso: string): string {
  if (!iso) return ""
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return "刚刚"
  if (diffMin < 60) return `${diffMin}分钟前`
  if (diffMin < 1440) return `${Math.floor(diffMin / 60)}小时前`
  if (diffMin < 10080) return `${Math.floor(diffMin / 1440)}天前`
  return d.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" })
}

export default function AlertRow({ alert, onAck, className }: AlertRowProps) {
  const href = buildDetailHref(alert)
  const isUnread = alert.status === "new"
  return (
    <div className={cn(
      "flex items-stretch gap-2 py-2 px-2 rounded transition-colors duration-150",
      "hover:bg-muted/40 border-b border-border-soft last:border-b-0",
      !isUnread && "opacity-60",
      className
    )}>
      <SeverityBar severity={alert.severity} />
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2">
          <Link
            to={href}
            className={cn(
              "text-sm truncate",
              isUnread ? "text-foreground font-medium" : "text-muted-foreground"
            )}
          >
            {alert.title || `${ALERT_TYPE_LABELS[alert.alert_type]} · ${alert.app_name}`}
          </Link>
          <ExternalLink className="w-3 h-3 text-muted-foreground shrink-0" />
        </div>
        {alert.rule_triggered && (
          <div className="text-2xs text-muted-foreground mt-0.5">
            {alert.rule_triggered} · {formatTime(alert.fired_at)}
          </div>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <span className="text-2xs text-muted-foreground tabular-nums">
          {formatTime(alert.fired_at)}
        </span>
        {isUnread && onAck && (
          <button
            onClick={() => onAck(alert.id)}
            className="px-1.5 h-6 inline-flex items-center gap-1 text-2xs border border-border-soft rounded hover:bg-muted text-muted-foreground"
            title="标记已读"
          >
            <Check className="w-3 h-3" />
          </button>
        )}
      </div>
    </div>
  )
}
