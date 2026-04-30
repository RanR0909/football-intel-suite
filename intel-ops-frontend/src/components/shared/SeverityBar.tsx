import { cn } from "@/lib/utils"
import type { AlertSeverity } from "@/types/api"

const STYLE: Record<AlertSeverity, string> = {
  high: "bg-semantic-danger",
  mid:  "bg-semantic-warning",
  low:  "bg-muted-foreground/30",
}

interface SeverityBarProps {
  severity: AlertSeverity
  className?: string
}

export default function SeverityBar({ severity, className }: SeverityBarProps) {
  return (
    <span
      className={cn("inline-block w-1 self-stretch rounded-sm", STYLE[severity], className)}
      aria-label={`severity-${severity}`}
    />
  )
}
