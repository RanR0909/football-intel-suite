import { useMemo, useState } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import FilterChips from "@/components/shared/FilterChips"
import EmptyState from "@/components/shared/EmptyState"
import Pill from "@/components/shared/Pill"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useCandidates } from "@/hooks/api/useCandidates"
import { useUrlFilters } from "@/hooks/useUrlFilters"
import { TOPIC_LABELS, CATEGORY_LABELS } from "@/types/domain"
import type { Candidate, Topic, Category } from "@/types/api"
import { Copy, Check, X, Eye } from "lucide-react"
import { cn } from "@/lib/utils"
import { toast } from "sonner"

type ReviewStatus = "pending" | "accepted" | "rejected"

interface ReviewState {
  status: ReviewStatus
  reviewed_at: string
}

const STORAGE_KEY = "intel-ops:candidate-reviewed"

function loadReviewed(): Record<string, ReviewState> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch { return {} }
}
function saveReviewed(map: Record<string, ReviewState>) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(map))
}

export default function Candidates() {
  const { value, setValue } = useUrlFilters({
    topic: "", conf: "0.85", status: "pending",
  })
  const topic = value("topic")
  const conf = parseFloat(value("conf")) || 0.85
  const statusFilter = value("status") as ReviewStatus | "all" | ""

  const [reviewed, setReviewed] = useState<Record<string, ReviewState>>(() => loadReviewed())
  const [activeId, setActiveId] = useState<string | null>(null)

  const { data, isLoading, isError, refetch } = useCandidates({
    topic, conf_min: conf, limit: 500,
  })
  const all = data?.candidates || []

  const filtered = useMemo(() => {
    return all.filter((c) => {
      const r = reviewed[c.app_id]?.status || "pending"
      if (statusFilter && statusFilter !== "all") {
        return r === statusFilter
      }
      return true
    })
  }, [all, reviewed, statusFilter])

  const kpi = useMemo(() => ({
    total: all.length,
    pending: all.filter((c) => (reviewed[c.app_id]?.status || "pending") === "pending").length,
    accepted: all.filter((c) => reviewed[c.app_id]?.status === "accepted").length,
    rejected: all.filter((c) => reviewed[c.app_id]?.status === "rejected").length,
  }), [all, reviewed])

  function setStatus(c: Candidate, s: ReviewStatus | null) {
    const next = { ...reviewed }
    if (s) next[c.app_id] = { status: s, reviewed_at: new Date().toISOString() }
    else delete next[c.app_id]
    setReviewed(next)
    saveReviewed(next)
  }

  function copyJsonSnippet(c: Candidate) {
    const snippet = {
      [c.name]: {
        ios: parseInt(c.app_id) || c.app_id,
        app_id: c.app_id,
        bundle_id: c.bundle_id || "",
        is_baseline: false,
      },
    }
    navigator.clipboard.writeText(JSON.stringify(snippet, null, 2)).then(() => {
      toast.success("已复制 JSON 片段，粘进 data/competitors.json")
    }).catch(() => toast.error("复制失败"))
  }

  const active = activeId ? all.find((c) => c.app_id === activeId) : null

  return (
    <div>
      <PageHeader
        title="候选发现"
        subtitle="AI 分类的潜在新竞品 · 审阅状态仅本地存储（换设备会丢失）"
      />

      <KpiRow>
        <KpiCard label="本周新增" value={kpi.total} hint="符合门槛的候选" />
        <KpiCard label="待审阅" value={kpi.pending} />
        <KpiCard label="已采纳" value={kpi.accepted} />
        <KpiCard label="已拒绝" value={kpi.rejected} />
      </KpiRow>

      <div className="space-y-2 mb-3">
        <FilterChips
          label="topic"
          options={[
            { value: "", label: "全部" },
            { value: "football", label: TOPIC_LABELS.football },
            { value: "multi_sport", label: TOPIC_LABELS.multi_sport },
          ]}
          value={topic}
          onChange={(v) => setValue("topic", v)}
        />
        <FilterChips
          label="置信度"
          options={[
            { value: "0.7", label: "≥ 0.70" },
            { value: "0.85", label: "≥ 0.85" },
            { value: "0.95", label: "≥ 0.95" },
          ]}
          value={String(conf)}
          onChange={(v) => setValue("conf", v)}
        />
        <FilterChips
          label="状态"
          options={[
            { value: "pending", label: "待审阅" },
            { value: "accepted", label: "已采纳" },
            { value: "rejected", label: "已拒绝" },
            { value: "all", label: "全部" },
          ]}
          value={statusFilter}
          onChange={(v) => setValue("status", v)}
        />
      </div>

      <div className="px-3 py-2 mb-3 text-2xs text-muted-foreground bg-pill-amber-bg/30 border border-pill-amber-bg rounded-md">
        审阅状态仅本地保存。采纳后请用 [复制] 按钮把 JSON 片段贴入 <code className="font-mono">data/competitors.json</code>，由后端开发执行 migration。
      </div>

      {isLoading && <SkeletonTable rows={6} />}
      {isError && <EmptyState type="error" onRetry={() => refetch()} />}
      {!isLoading && !isError && filtered.length === 0 && <EmptyState type="empty" />}

      {filtered.length > 0 && (
        <div className="border border-border-soft rounded-md bg-card overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-muted/30 text-2xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left px-3 h-8">App</th>
                <th className="text-left px-3 h-8">发行商</th>
                <th className="text-left px-3 h-8">topic</th>
                <th className="text-left px-3 h-8">categories</th>
                <th className="text-right px-3 h-8">conf</th>
                <th className="text-right px-3 h-8">状态</th>
                <th className="text-right px-3 h-8">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-soft">
              {filtered.map((c) => {
                const status = reviewed[c.app_id]?.status || "pending"
                return (
                  <tr key={c.app_id} className="hover:bg-muted/30">
                    <td className="px-3 h-9">
                      <button
                        onClick={() => setActiveId(c.app_id)}
                        className="font-medium hover:text-brand-700 text-left"
                      >
                        {c.name}
                      </button>
                      <div className="text-2xs text-muted-foreground font-mono">
                        {c.platform}:{c.app_id}
                      </div>
                    </td>
                    <td className="px-3 h-9 text-muted-foreground truncate max-w-[120px]">
                      {c.publisher || "—"}
                    </td>
                    <td className="px-3 h-9">
                      <Pill variant="blue">{TOPIC_LABELS[c.topic as Topic] || c.topic}</Pill>
                    </td>
                    <td className="px-3 h-9">
                      <div className="flex gap-1 flex-wrap">
                        {(c.categories as Category[]).slice(0, 4).map((cat) => (
                          <Pill key={cat} variant="gray">
                            {CATEGORY_LABELS[cat] || cat}
                          </Pill>
                        ))}
                      </div>
                    </td>
                    <td className="px-3 h-9 text-right tabular-nums font-mono">
                      {c.confidence.toFixed(2)}
                    </td>
                    <td className="px-3 h-9 text-right">
                      <Pill variant={status === "accepted" ? "green" : status === "rejected" ? "red" : "amber"}>
                        {status === "pending" ? "待审" : status === "accepted" ? "已采纳" : "已拒绝"}
                      </Pill>
                    </td>
                    <td className="px-3 h-9 text-right">
                      <div className="inline-flex gap-1">
                        <button onClick={() => setActiveId(c.app_id)} className="p-1 rounded hover:bg-muted text-muted-foreground" title="详情">
                          <Eye className="w-3 h-3" />
                        </button>
                        <button
                          onClick={() => setStatus(c, "accepted")}
                          className={cn("p-1 rounded hover:bg-pill-green-bg text-muted-foreground hover:text-pill-green-fg",
                            status === "accepted" && "bg-pill-green-bg text-pill-green-fg")}
                          title="标记已采纳"
                        >
                          <Check className="w-3 h-3" />
                        </button>
                        <button
                          onClick={() => setStatus(c, "rejected")}
                          className={cn("p-1 rounded hover:bg-pill-red-bg text-muted-foreground hover:text-pill-red-fg",
                            status === "rejected" && "bg-pill-red-bg text-pill-red-fg")}
                          title="标记已拒绝"
                        >
                          <X className="w-3 h-3" />
                        </button>
                        <button
                          onClick={() => copyJsonSnippet(c)}
                          className="p-1 rounded hover:bg-brand-50 text-muted-foreground hover:text-brand-700"
                          title="复制 competitors.json 片段"
                        >
                          <Copy className="w-3 h-3" />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {active && (
        <div className="fixed inset-0 bg-black/30 z-40 flex items-start justify-end" onClick={() => setActiveId(null)}>
          <div className="w-full max-w-md h-full bg-card border-l border-border overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="px-4 py-3 border-b border-border-soft flex items-center justify-between sticky top-0 bg-card">
              <span className="text-sm font-semibold">{active.name}</span>
              <button onClick={() => setActiveId(null)} className="p-1 rounded hover:bg-muted">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="px-4 py-3 text-xs space-y-3">
              <Field label="发行商" value={active.publisher} />
              <Field label="平台 / app_id" value={`${active.platform} · ${active.app_id}`} />
              <Field label="bundle_id" value={active.bundle_id} mono />
              <Field label="store category" value={active.category} />
              <Field label="AI topic" value={TOPIC_LABELS[active.topic as Topic] || active.topic} />
              <Field
                label="AI categories"
                value={
                  <div className="flex flex-wrap gap-1">
                    {(active.categories as Category[]).map((cat) => (
                      <Pill key={cat} variant="gray">{CATEGORY_LABELS[cat] || cat}</Pill>
                    ))}
                  </div>
                }
              />
              <Field label="confidence" value={active.confidence.toFixed(2)} mono />
              {active.matched_keywords?.length > 0 && (
                <Field
                  label="matched keywords"
                  value={
                    <div className="flex flex-wrap gap-1">
                      {active.matched_keywords.map((kw) => (
                        <Pill key={kw} variant="amber">{kw}</Pill>
                      ))}
                    </div>
                  }
                />
              )}
              {active.rejection_reason && <Field label="rejection reason" value={active.rejection_reason} />}
              {active.description_excerpt && (
                <Field
                  label="description"
                  value={
                    <p className="text-2xs text-muted-foreground leading-snug whitespace-pre-wrap">
                      {active.description_excerpt}
                    </p>
                  }
                />
              )}
              <Field label="classified_at" value={new Date(active.classified_at).toLocaleString("zh-CN")} mono />
              <button
                onClick={() => copyJsonSnippet(active)}
                className="w-full px-3 h-8 inline-flex items-center justify-center gap-1 text-xs font-medium border border-border rounded hover:bg-brand-50 hover:text-brand-700 hover:border-brand-300"
              >
                <Copy className="w-3 h-3" /> 复制 competitors.json 片段
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Field({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div>
      <div className="text-2xs uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={cn("mt-0.5", mono && "font-mono")}>{value || "—"}</div>
    </div>
  )
}
