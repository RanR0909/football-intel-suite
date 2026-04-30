import { cn } from "@/lib/utils"

interface KpiCardProps {
  label: string
  value: React.ReactNode
  hint?: string
  trend?: { dir: "up" | "down" | "flat"; text: string } | null
  className?: string
}

export default function KpiCard({ label, value, hint, trend, className }: KpiCardProps) {
  return (
    <div className={cn(
      "border border-border-soft rounded-md bg-card p-3 min-h-[68px]",
      className
    )}>
      <div className="text-2xs text-muted-foreground uppercase tracking-wider">
        {label}
      </div>
      <div className="text-2xl font-semibold tabular-nums mt-1">
        {value ?? "—"}
      </div>
      <div className="flex items-center gap-2 mt-0.5 text-2xs">
        {trend && (
          <span className={cn(
            "tabular-nums",
            trend.dir === "up" && "text-semantic-success",
            trend.dir === "down" && "text-semantic-danger",
            trend.dir === "flat" && "text-muted-foreground"
          )}>
            {trend.text}
          </span>
        )}
        {hint && <span className="text-muted-foreground">{hint}</span>}
      </div>
    </div>
  )
}

interface KpiRowProps {
  children: React.ReactNode
}

export function KpiRow({ children }: KpiRowProps) {
  return <div className="grid grid-cols-4 gap-3 mb-4">{children}</div>
}
