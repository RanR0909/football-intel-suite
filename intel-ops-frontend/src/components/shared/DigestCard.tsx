import { Link } from "react-router-dom"
import { ArrowUpRight } from "lucide-react"
import { cn } from "@/lib/utils"

interface DigestCardProps {
  title: string
  /** 分类 pill — 内容/数据；省略则不显示 pill（更紧凑） */
  category?: "data" | "content"
  meta?: string
  detailHref: string
  className?: string
  children?: React.ReactNode
  /** 紧凑模式：title + emptyMsg + 详情→ 单行展示，children 不渲染 */
  collapsed?: boolean
  emptyMsg?: string
}

const CATEGORY_PILL = {
  data:    { text: "数据", className: "bg-pill-blue-bg text-pill-blue-fg" },
  content: { text: "内容", className: "bg-pill-purple-bg text-pill-purple-fg" },
}

export default function DigestCard({
  title, category, meta, detailHref, className, children,
  collapsed, emptyMsg,
}: DigestCardProps) {
  const pill = category ? CATEGORY_PILL[category] : null

  if (collapsed) {
    return (
      <div className={cn(
        "border border-border-soft rounded-md bg-card px-3 py-2 flex items-center gap-2 text-xs",
        className
      )}>
        <span className="font-medium">{title}</span>
        {emptyMsg && (
          <span className="text-2xs text-muted-foreground font-mono">{emptyMsg}</span>
        )}
        <Link
          to={detailHref}
          className="ml-auto text-2xs text-muted-foreground hover:text-foreground inline-flex items-center gap-0.5"
        >
          详情 <ArrowUpRight className="w-3 h-3" />
        </Link>
      </div>
    )
  }

  return (
    <div className={cn(
      "border border-border-soft rounded-md bg-card p-4 flex flex-col",
      className
    )}>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-base font-semibold tracking-tight">{title}</span>
        {pill && (
          <span className={cn("text-2xs px-1.5 py-0.5 rounded font-medium", pill.className)}>
            {pill.text}
          </span>
        )}
        <Link
          to={detailHref}
          className="ml-auto text-2xs text-muted-foreground hover:text-foreground inline-flex items-center gap-0.5"
        >
          详情 <ArrowUpRight className="w-3 h-3" />
        </Link>
      </div>
      {meta && (
        <div className="text-xs text-muted-foreground mb-2">{meta}</div>
      )}
      <div className="flex-1">
        {children}
      </div>
    </div>
  )
}
