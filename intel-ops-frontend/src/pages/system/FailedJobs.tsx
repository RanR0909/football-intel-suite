import { useState, useMemo } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import FilterChips from "@/components/shared/FilterChips"
import EmptyState from "@/components/shared/EmptyState"
import Pill from "@/components/shared/Pill"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useFailedAiJobs, useRetryAiJob } from "@/hooks/api/useFailedAiJobs"
import { useUrlFilters } from "@/hooks/useUrlFilters"
import { RefreshCw, Eye, X } from "lucide-react"
import type { FailedAiJob } from "@/types/api"

const TASK_OPTIONS = [
  { value: "", label: "全部" },
  { value: "ad_selling_point", label: "ad_selling_point" },
  { value: "entity_extract", label: "entity_extract" },
  { value: "post_entity_extract", label: "post_entity_extract" },
  { value: "comment_label", label: "comment_label" },
  { value: "news_classifier", label: "news_classifier" },
  { value: "post_topic", label: "post_topic" },
  { value: "alert_title", label: "alert_title" },
  { value: "app_classifier", label: "app_classifier" },
]

const STATUS_OPTIONS = [
  { value: "false", label: "未解决" },
  { value: "true", label: "已解决" },
  { value: "", label: "全部" },
]

const SCOPE_OPTIONS = [
  { value: "true",  label: "最近一轮 (6h)" },
  { value: "false", label: "全部历史" },
]

export default function FailedJobs() {
  const { value, setValue } = useUrlFilters({ task: "", resolved: "false", scope: "true" })
  const task = value("task")
  const resolved = value("resolved") as "true" | "false" | ""
  const scope = value("scope") as "true" | "false"
  const latestRound = scope !== "false"

  const [activeId, setActiveId] = useState<number | null>(null)

  const { data, isLoading, isError, refetch } = useFailedAiJobs({
    task, resolved: resolved || undefined,
    latest_round: latestRound, limit: 500,
  })
  const { mutate: retry, isPending } = useRetryAiJob()
  const all = data?.jobs || []

  const kpi = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const j of all) counts[j.task_name] = (counts[j.task_name] || 0) + 1
    const top3 = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 3)
    return { total: all.length, top3 }
  }, [all])

  const active = activeId ? all.find((j) => j.id === activeId) : null

  return (
    <div>
      <PageHeader
        title="AI 失败队列"
        subtitle={
          latestRound
            ? "重试耗尽的 AI 任务 · 默认只看每个 task 最近 6h 内的失败（切换“全部历史”看全量）"
            : "重试耗尽的 AI 任务 · 全部历史"
        }
      />

      <KpiRow>
        <KpiCard
          label={latestRound ? "本轮未解决" : "未解决总数"}
          value={kpi.total}
        />
        <KpiCard
          label={kpi.top3[0]?.[0] || "—"}
          value={kpi.top3[0]?.[1] ?? "—"}
        />
        <KpiCard
          label={kpi.top3[1]?.[0] || "—"}
          value={kpi.top3[1]?.[1] ?? "—"}
        />
        <KpiCard
          label={kpi.top3[2]?.[0] || "—"}
          value={kpi.top3[2]?.[1] ?? "—"}
        />
      </KpiRow>

      <div className="space-y-2 mb-3">
        <FilterChips label="范围" options={SCOPE_OPTIONS} value={scope} onChange={(v) => setValue("scope", v)} />
        <FilterChips label="task" options={TASK_OPTIONS} value={task} onChange={(v) => setValue("task", v)} />
        <FilterChips label="状态" options={STATUS_OPTIONS} value={resolved} onChange={(v) => setValue("resolved", v)} />
      </div>

      {isLoading && <SkeletonTable rows={6} />}
      {isError && <EmptyState type="error" onRetry={() => refetch()} />}
      {!isLoading && !isError && all.length === 0 && (
        <EmptyState type="empty" hint="无失败任务（恭喜）" />
      )}

      {all.length > 0 && (
        <div className="border border-border-soft rounded-md bg-card overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-muted/30 text-2xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left px-3 h-8">task</th>
                <th className="text-left px-3 h-8">error_kind</th>
                <th className="text-left px-3 h-8">error_msg 摘要</th>
                <th className="text-right px-3 h-8">尝试</th>
                <th className="text-right px-3 h-8">最近尝试</th>
                <th className="text-right px-3 h-8">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-soft">
              {all.map((j) => (
                <tr key={j.id} className="hover:bg-muted/30">
                  <td className="px-3 h-9 font-mono">{j.task_name}</td>
                  <td className="px-3 h-9">
                    {j.error_kind ? <Pill variant="red">{j.error_kind}</Pill> : "—"}
                  </td>
                  <td className="px-3 h-9 text-muted-foreground truncate max-w-md">
                    {j.error_msg?.slice(0, 80) || "—"}
                  </td>
                  <td className="px-3 h-9 text-right tabular-nums">{j.attempts}</td>
                  <td className="px-3 h-9 text-right tabular-nums text-muted-foreground">
                    {j.last_attempt_at ? new Date(j.last_attempt_at).toLocaleString("zh-CN") : "—"}
                  </td>
                  <td className="px-3 h-9 text-right">
                    <div className="inline-flex gap-1">
                      <button
                        onClick={() => setActiveId(j.id)}
                        className="p-1 rounded hover:bg-muted"
                        title="详情"
                      >
                        <Eye className="w-3 h-3" />
                      </button>
                      {!j.resolved_at && (
                        <button
                          onClick={() => retry(j.id)}
                          disabled={isPending}
                          className="p-1 rounded hover:bg-brand-50 hover:text-brand-700 disabled:opacity-50"
                          title="重试"
                        >
                          <RefreshCw className={isPending ? "w-3 h-3 animate-spin" : "w-3 h-3"} />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {active && <JobDetailDrawer job={active} onClose={() => setActiveId(null)} onRetry={() => retry(active.id)} />}
    </div>
  )
}

function JobDetailDrawer({ job, onClose, onRetry }:
  { job: FailedAiJob; onClose: () => void; onRetry: () => void }) {
  return (
    <div className="fixed inset-0 bg-black/30 z-40 flex items-start justify-end" onClick={onClose}>
      <div className="w-full max-w-lg h-full bg-card border-l border-border overflow-y-auto"
        onClick={(e) => e.stopPropagation()}>
        <div className="px-4 py-3 border-b border-border-soft flex items-center justify-between sticky top-0 bg-card">
          <span className="text-sm font-semibold font-mono">{job.task_name} #{job.id}</span>
          <button onClick={onClose} className="p-1 rounded hover:bg-muted">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-4 py-3 text-xs space-y-3">
          <Block label="error_kind">
            {job.error_kind ? <Pill variant="red">{job.error_kind}</Pill> : "—"}
          </Block>
          <Block label="attempts">
            <span className="font-mono tabular-nums">{job.attempts}</span>
          </Block>
          <Block label="error_msg">
            <pre className="text-2xs bg-muted/40 p-2 rounded overflow-x-auto whitespace-pre-wrap break-words">
              {job.error_msg || "—"}
            </pre>
          </Block>
          <Block label="payload (调用 context)">
            <pre className="text-2xs bg-muted/40 p-2 rounded overflow-x-auto">
              {JSON.stringify(job.payload, null, 2)}
            </pre>
          </Block>
          <Block label="时间线">
            <ul className="text-2xs space-y-0.5 font-mono tabular-nums">
              <li>首次失败：{new Date(job.first_failed_at).toLocaleString("zh-CN")}</li>
              <li>最近尝试：{new Date(job.last_attempt_at).toLocaleString("zh-CN")}</li>
              {job.resolved_at && <li>已解决：{new Date(job.resolved_at).toLocaleString("zh-CN")}</li>}
            </ul>
          </Block>
          {!job.resolved_at && (
            <button
              onClick={onRetry}
              className="w-full px-3 h-8 text-xs font-medium border border-border rounded hover:bg-brand-50 hover:text-brand-700 hover:border-brand-300"
            >
              手动重试
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function Block({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-2xs uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1">{children}</div>
    </div>
  )
}
