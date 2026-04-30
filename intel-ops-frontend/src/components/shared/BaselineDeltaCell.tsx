import { cn } from "@/lib/utils"
import type { BaselineDelta } from "@/lib/baseline"

interface BaselineDeltaCellProps {
  delta: BaselineDelta
  className?: string
}

export default function BaselineDeltaCell({ delta, className }: BaselineDeltaCellProps) {
  return (
    <span className={cn(
      "tabular-nums",
      delta.color === "danger" && "text-semantic-danger",
      delta.color === "success" && "text-semantic-success",
      delta.color === "neutral" && "text-muted-foreground",
      className
    )}>
      {delta.display}
    </span>
  )
}
