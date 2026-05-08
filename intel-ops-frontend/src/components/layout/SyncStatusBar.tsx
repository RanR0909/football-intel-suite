import { useStatus } from "@/hooks/api/useDashboardData"
import { cn } from "@/lib/utils"
import { CheckCircle2, XCircle, Clock, MinusCircle } from "lucide-react"

type Status = "ok" | "fail" | "pending" | "unknown"

const STATUS_STYLE: Record<Status, { icon: React.ElementType; color: string }> = {
  ok:      { icon: CheckCircle2, color: "text-semantic-success" },
  fail:    { icon: XCircle,      color: "text-semantic-danger" },
  pending: { icon: Clock,        color: "text-semantic-warning" },
  unknown: { icon: MinusCircle,  color: "text-muted-foreground" },
}

/** fb_adlib_us / fb_adlib_gb / ... 折叠成单个 fb_adlib bucket — 每国一行徽章太挤。
 *  bucket status = 任一失败 → fail；全 ok → ok；其它 → pending。 */
const PER_COUNTRY_PREFIXES = ["fb_adlib_"]

/** 从 sources map 折叠 per-country bucket，并按状态/字母序排序。 */
function collapseAndSort(sources: Record<string, { status?: string; last_success?: string | null }>) {
  const buckets: Record<string, { status: Status; last_success: string | null; members: string[] }> = {}
  for (const [name, s] of Object.entries(sources)) {
    const prefix = PER_COUNTRY_PREFIXES.find((p) => name.startsWith(p) && name.length > p.length)
    const key = prefix ? prefix.replace(/_$/, "") : name
    const st = (s?.status as Status) || "unknown"
    if (!buckets[key]) {
      buckets[key] = { status: st, last_success: s?.last_success ?? null, members: [name] }
      continue
    }
    const cur = buckets[key]
    cur.members.push(name)
    // 任一失败 → bucket fail；否则任一 pending → pending；都 ok → ok
    if (st === "fail" || cur.status === "fail") cur.status = "fail"
    else if (st === "pending" || cur.status === "pending") cur.status = "pending"
    else cur.status = "ok"
    // 取最新的 last_success（折叠后的代表值）
    if (s?.last_success && (!cur.last_success || s.last_success > cur.last_success)) {
      cur.last_success = s.last_success
    }
  }
  // 排序：fail 优先 → pending → ok → unknown，同级按字母
  const order: Record<Status, number> = { fail: 0, pending: 1, ok: 2, unknown: 3 }
  return Object.entries(buckets).sort(([an, av], [bn, bv]) => {
    const oa = order[av.status]
    const ob = order[bv.status]
    if (oa !== ob) return oa - ob
    return an.localeCompare(bn)
  })
}

export default function SyncStatusBar() {
  const { data, isLoading } = useStatus()

  const sources = data?.sources ?? {}
  const failed = Object.values(data?.failed_ai_jobs || {}).reduce(
    (a: number, b) => a + (typeof b === "number" ? b : 0),
    0,
  )
  const queueSize = data?.retry_queue_size ?? 0

  const collapsed = collapseAndSort(sources)

  const overall: Status = (() => {
    if (isLoading) return "pending"
    if (collapsed.length === 0) return "unknown"
    const stats = collapsed.map(([, v]) => v.status)
    if (stats.some((s) => s === "fail")) return "fail"
    if (stats.some((s) => s === "pending")) return "pending"
    if (stats.every((s) => s === "ok")) return "ok"
    return "unknown"
  })()

  const overallStyle = STATUS_STYLE[overall]
  const OverallIcon = overallStyle.icon

  return (
    <div className="flex items-center gap-3 px-3 py-2 border border-border-soft rounded-md bg-card text-xs">
      <div className={cn("flex items-center gap-1.5 shrink-0", overallStyle.color)}>
        <OverallIcon className="w-3.5 h-3.5" />
        <span className="font-medium">
          {overall === "ok" && "同步 OK"}
          {overall === "fail" && "有失败"}
          {overall === "pending" && "重试中"}
          {overall === "unknown" && "未知"}
        </span>
      </div>
      <div className="text-muted-foreground shrink-0">
        retry queue: {queueSize} · failed AI: {failed}
      </div>
      <div className="flex-1 flex flex-wrap gap-1 min-w-0">
        {collapsed.map(([name, v]) => {
          const style = STATUS_STYLE[v.status]
          const memberHint = v.members.length > 1 ? ` (×${v.members.length})` : ""
          const lastHint = v.last_success ? ` · last_success: ${v.last_success}` : ""
          return (
            <div
              key={name}
              className={cn(
                "inline-flex items-center gap-1 px-1.5 h-5 rounded bg-muted/40 text-2xs",
                style.color,
              )}
              title={`${name}${memberHint}: ${v.status}${lastHint}`}
            >
              <style.icon className="w-3 h-3" />
              <span className="font-mono">{name}{memberHint}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
