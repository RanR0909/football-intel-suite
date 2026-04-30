import { useMemo } from "react"
import PageHeader from "@/components/shared/PageHeader"
import AlertRow from "@/components/shared/AlertRow"
import FilterChips from "@/components/shared/FilterChips"
import EmptyState from "@/components/shared/EmptyState"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useAlerts, useAckAlert } from "@/hooks/api/useAlerts"
import { useUrlFilters } from "@/hooks/useUrlFilters"
import { ALERT_TYPE_LABELS } from "@/types/domain"
import type { Alert, AlertType } from "@/types/api"

const TIME_OPTIONS = [
  { value: "24h", label: "今日" },
  { value: "48h", label: "昨日" },
  { value: "7d",  label: "7d" },
  { value: "30d", label: "30d" },
]

const TYPE_OPTIONS = [
  { value: "",           label: "全部" },
  { value: "ranking",    label: "排名" },
  { value: "commercial", label: "商业" },
  { value: "news",       label: "新闻" },
  { value: "release",    label: "发版" },
  { value: "rating",     label: "评分" },
  { value: "churn",      label: "流失" },
  { value: "ads",        label: "广告" },
]

const SEVERITY_OPTIONS = [
  { value: "",      label: "全部" },
  { value: "high",  label: "high" },
  { value: "mid",   label: "mid" },
  { value: "low",   label: "low" },
]

const STATUS_OPTIONS = [
  { value: "",         label: "全部" },
  { value: "new",      label: "未读" },
  { value: "ack",      label: "已读" },
  { value: "dismissed",label: "已忽略" },
]

export default function AlertCenter() {
  const { value, setValue } = useUrlFilters({
    since: "7d", type: "", severity: "", status: "",
  })
  const since = value("since")
  const type = value("type")
  const severity = value("severity")
  const status = value("status")

  const { data, isLoading, isError, refetch } = useAlerts({
    since, type, severity, status, limit: 500,
  })
  const { mutate: ackAlert } = useAckAlert()

  const grouped = useMemo(() => {
    if (!data?.alerts) return new Map<AlertType, Alert[]>()
    const m = new Map<AlertType, Alert[]>()
    for (const a of data.alerts) {
      if (!m.has(a.alert_type)) m.set(a.alert_type, [])
      m.get(a.alert_type)!.push(a)
    }
    // 按 ALERT_TYPE_LABELS 顺序输出
    const ordered = new Map<AlertType, Alert[]>()
    for (const k of Object.keys(ALERT_TYPE_LABELS) as AlertType[]) {
      const arr = m.get(k)
      if (arr && arr.length) ordered.set(k, arr)
    }
    return ordered
  }, [data])

  return (
    <div>
      <PageHeader
        title="预警中心"
        subtitle="7 类预警事件流（数据驱动 + AI 写 ≤50 字事实陈述）"
        right={
          data && (
            <span className="text-xs text-muted-foreground tabular-nums">
              共 {data.count} 条
            </span>
          )
        }
      />

      <div className="mb-4 space-y-2">
        <FilterChips label="时间" options={TIME_OPTIONS} value={since}
          onChange={(v) => setValue("since", v)} />
        <FilterChips label="类型" options={TYPE_OPTIONS} value={type}
          onChange={(v) => setValue("type", v)} />
        <FilterChips label="严重度" options={SEVERITY_OPTIONS} value={severity}
          onChange={(v) => setValue("severity", v)} />
        <FilterChips label="状态" options={STATUS_OPTIONS} value={status}
          onChange={(v) => setValue("status", v)} />
      </div>

      {isLoading && <SkeletonTable rows={6} />}
      {isError && <EmptyState type="error" onRetry={() => refetch()} />}
      {!isLoading && !isError && grouped.size === 0 && (
        <EmptyState type="empty" hint="当前筛选条件下无事件" />
      )}

      {grouped.size > 0 && (
        <div className="space-y-4">
          {[...grouped.entries()].map(([atype, arr]) => (
            <section
              key={atype}
              className="border border-border-soft rounded-md bg-card overflow-hidden"
            >
              <header className="flex items-center justify-between px-3 h-9 bg-muted/30 border-b border-border-soft">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{ALERT_TYPE_LABELS[atype]}</span>
                  <span className="text-2xs text-muted-foreground">{arr.length} 条</span>
                </div>
                <span className="text-2xs text-muted-foreground font-mono">{atype}</span>
              </header>
              <div className="px-2">
                {arr.map((a) => (
                  <AlertRow key={a.id} alert={a} onAck={(id) => ackAlert(id)} />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
