import { useMemo, useState } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import FilterChips from "@/components/shared/FilterChips"
import EmptyState from "@/components/shared/EmptyState"
import Pill from "@/components/shared/Pill"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useSyncLog } from "@/hooks/api/useSyncLog"
import { useStatus } from "@/hooks/api/useDashboardData"
import { useUrlFilters } from "@/hooks/useUrlFilters"
import { Eye, X } from "lucide-react"
import type { SyncLogEntry } from "@/types/api"
import { cn } from "@/lib/utils"

const STATUS_OPTIONS = [
  { value: "", label: "全部" },
  { value: "success", label: "成功" },
  { value: "fail", label: "失败" },
]

export default function SyncLog() {
  const { value, setValue } = useUrlFilters({ source: "", status: "" })
  const source = value("source")
  const status = value("status") as "success" | "fail" | ""
  const [activeId, setActiveId] = useState<number | null>(null)

  const { data, isLoading, isError, refetch } = useSyncLog({
    source, status, limit: 100,
  })
  // 拉一份不带 source 过滤的 logs，用于组装下拉的 SOURCE_OPTIONS。
  // 否则用户一旦选了某 source，下拉会塌缩到只剩那一个选项 — 没法切回别的。
  const { data: allSourcesData } = useSyncLog({ status: "", limit: 200 })
  const { data: statusData } = useStatus()
  const all = data?.logs || []
  const active = activeId ? all.find((l) => l.id === activeId) : null

  // 动态 source 列表：sync_log.script ∪ status.sources keys（覆盖最近没跑过的源）
  const SOURCE_OPTIONS = useMemo(() => {
    const set = new Set<string>()
    for (const l of allSourcesData?.logs || []) {
      if (l.script) set.add(l.script)
    }
    for (const k of Object.keys(statusData?.sources || {})) {
      set.add(k)
    }
    return [
      { value: "", label: "全部" },
      ...Array.from(set).sort().map((s) => ({ value: s, label: s })),
    ]
  }, [allSourcesData, statusData])

  const kpi = useMemo(() => {
    const ok = all.filter((l) => l.success).length
    const total = all.length
    const successRate = total ? `${((ok / total) * 100).toFixed(0)}%` : "—"
    const avgDur = total
      ? (all.reduce((s, l) => s + (l.duration_sec || 0), 0) / total).toFixed(1) + "s"
      : "—"
    const lastSuccess = all.find((l) => l.success)?.started_at
    return {
      successRate,
      lastSuccess: lastSuccess ? new Date(lastSuccess).toLocaleString("zh-CN", {
        month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"
      }) : "—",
      retry: statusData?.retry_queue_size ?? 0,
      avgDur,
    }
  }, [all, statusData])

  return (
    <div>
      <PageHeader title="同步日志" />

      <KpiRow>
        <KpiCard label="近 50 次成功率" value={kpi.successRate} />
        <KpiCard label="最近成功" value={kpi.lastSuccess} />
        <KpiCard label="retry queue" value={kpi.retry} hint="待重跑" />
        <KpiCard label="平均耗时" value={kpi.avgDur} />
      </KpiRow>

      <div className="space-y-2 mb-3">
        <FilterChips label="source" options={SOURCE_OPTIONS} value={source} onChange={(v) => setValue("source", v)} />
        <FilterChips label="状态" options={STATUS_OPTIONS} value={status} onChange={(v) => setValue("status", v)} />
      </div>

      {isLoading && <SkeletonTable rows={8} />}
      {isError && <EmptyState type="error" onRetry={() => refetch()} />}
      {!isLoading && !isError && all.length === 0 && <EmptyState type="empty" />}

      {all.length > 0 && (
        <div className="border border-border-soft rounded-md bg-card overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-muted/30 text-2xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left px-3 h-8">source</th>
                <th className="text-left px-3 h-8">started_at</th>
                <th className="text-right px-3 h-8">duration</th>
                <th className="text-left px-3 h-8">状态</th>
                <th className="text-left px-3 h-8">competitor</th>
                <th className="text-right px-3 h-8">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-soft">
              {all.map((l) => (
                <tr key={l.id} className={cn("hover:bg-muted/30", !l.success && "bg-pill-red-bg/20")}>
                  <td className="px-3 h-9 font-mono">{l.script}</td>
                  <td className="px-3 h-9 tabular-nums text-muted-foreground">
                    {new Date(l.started_at).toLocaleString("zh-CN", {
                      month: "2-digit", day: "2-digit",
                      hour: "2-digit", minute: "2-digit", second: "2-digit",
                    })}
                  </td>
                  <td className="px-3 h-9 text-right tabular-nums">
                    {l.duration_sec != null ? `${l.duration_sec.toFixed(1)}s` : "—"}
                  </td>
                  <td className="px-3 h-9">
                    {l.success ? <Pill variant="green">成功</Pill> : <Pill variant="red">{l.error_kind || "失败"}</Pill>}
                  </td>
                  <td className="px-3 h-9 text-muted-foreground">{l.competitor || "—"}</td>
                  <td className="px-3 h-9 text-right">
                    <button onClick={() => setActiveId(l.id)} className="p-1 rounded hover:bg-muted" title="详情">
                      <Eye className="w-3 h-3" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {active && <LogDetailDrawer log={active} onClose={() => setActiveId(null)} />}
    </div>
  )
}

function LogDetailDrawer({ log, onClose }: { log: SyncLogEntry; onClose: () => void }) {
  return (
    <div className="fixed inset-0 bg-black/30 z-40 flex items-start justify-end" onClick={onClose}>
      <div className="w-full max-w-2xl h-full bg-card border-l border-border overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="px-4 py-3 border-b border-border-soft flex items-center justify-between sticky top-0 bg-card">
          <span className="text-sm font-semibold font-mono">{log.script}</span>
          <button onClick={onClose} className="p-1 rounded hover:bg-muted">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-4 py-3 text-xs space-y-3">
          <div>
            <div className="text-2xs uppercase text-muted-foreground">命令行</div>
            <pre className="mt-1 font-mono text-2xs bg-muted/40 p-2 rounded overflow-x-auto whitespace-pre-wrap break-words">
              {log.cmd || "—"}
            </pre>
          </div>
          {log.stdout_tail && (
            <div>
              <div className="text-2xs uppercase text-muted-foreground">stdout (tail)</div>
              <pre className="mt-1 font-mono text-2xs bg-muted/40 p-2 rounded overflow-x-auto whitespace-pre-wrap max-h-60 overflow-y-auto">
                {log.stdout_tail}
              </pre>
            </div>
          )}
          {log.stderr_tail && (
            <div>
              <div className="text-2xs uppercase text-muted-foreground">stderr (tail)</div>
              <pre className="mt-1 font-mono text-2xs bg-pill-red-bg/30 text-pill-red-fg p-2 rounded overflow-x-auto whitespace-pre-wrap max-h-60 overflow-y-auto">
                {log.stderr_tail}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
