import { AlertCircle, Inbox, RefreshCw } from "lucide-react"
import { cn } from "@/lib/utils"

interface EmptyStateProps {
  type?: "empty" | "error" | "loading"
  title?: string
  hint?: string
  onRetry?: () => void
  className?: string
}

export default function EmptyState({
  type = "empty",
  title,
  hint,
  onRetry,
  className,
}: EmptyStateProps) {
  const config = {
    empty:   { icon: Inbox,       title: title || "暂无数据",   hint: hint || "等抓取作业完成后再看" },
    error:   { icon: AlertCircle, title: title || "加载失败",   hint: hint || "稍后重试或检查后端 API" },
    loading: { icon: RefreshCw,   title: title || "加载中…",    hint: hint || "" },
  }[type]

  const Icon = config.icon

  return (
    <div className={cn(
      "flex flex-col items-center justify-center py-16 text-muted-foreground",
      className
    )}>
      <Icon className={cn("w-8 h-8 mb-3", type === "loading" && "animate-spin")} />
      <div className="text-sm font-medium">{config.title}</div>
      {config.hint && (
        <div className="text-xs mt-1">{config.hint}</div>
      )}
      {onRetry && type === "error" && (
        <button
          onClick={onRetry}
          className="mt-4 px-3 h-8 text-xs border border-border rounded hover:bg-muted"
        >
          重试
        </button>
      )}
    </div>
  )
}
