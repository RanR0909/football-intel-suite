import PageHeader from "./PageHeader"

interface PagePlaceholderProps {
  title: string
  subtitle?: string
  stage?: string
}

/** Stage 1 占位组件 — 阶段 2/3 时逐页替换为真实内容 */
export default function PagePlaceholder({ title, subtitle, stage }: PagePlaceholderProps) {
  return (
    <div>
      <PageHeader title={title} subtitle={subtitle} />
      <div className="border border-dashed border-border rounded-md p-12 text-center">
        <div className="text-sm font-medium text-muted-foreground">
          🚧 建设中 · {stage || "Stage 2"} 实现
        </div>
        <div className="text-xs text-muted-foreground mt-1">
          参考 INTEL-OPS_前端实现文档_v2.md §9
        </div>
      </div>
    </div>
  )
}
