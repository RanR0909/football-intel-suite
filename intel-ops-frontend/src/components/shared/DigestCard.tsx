import { Link } from "react-router-dom"
import { ArrowUpRight } from "lucide-react"
import { cn } from "@/lib/utils"

interface DigestCardProps {
  title: string
  category: "data" | "content"
  meta?: string
  detailHref: string
  className?: string
  children?: React.ReactNode
}

const CATEGORY_PILL = {
  data:    { text: "数据", className: "bg-pill-blue-bg text-pill-blue-fg" },
  content: { text: "内容", className: "bg-pill-purple-bg text-pill-purple-fg" },
}

export default function DigestCard({
  title, category, meta, detailHref, className, children,
}: DigestCardProps) {
  const pill = CATEGORY_PILL[category]
  return (
    <div className={cn(
      "border border-border-soft rounded-md bg-card p-4 flex flex-col",
      className
    )}>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-base font-semibold tracking-tight">{title}</span>
        <span className={cn("text-2xs px-1.5 py-0.5 rounded font-medium", pill.className)}>
          {pill.text}
        </span>
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
