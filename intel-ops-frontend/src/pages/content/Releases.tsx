/** 产品动态页（spec 前端实现文档 §9.7 + wireframe 03 升级版）
 *
 * 改造（task 10/11 上线后）:
 *  · 卡头直接展示价值信号：版本类型 Pill + 1-3 个中文亮点 + ⭐ 重要标
 *  · 重要更新（is_significant=true）默认置顶；普通 bugfix 下沉
 *  · KPI 用 version_type 真统计（不再 regex 命中"new"/"feature"虚高）
 *  · 展开后 release_notes 优先显示中文翻译
 *  · 修了 related_reviews rating_change SQL bug (reviews.rating → score)
 */
import { useMemo, useState } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import EmptyState from "@/components/shared/EmptyState"
import Pill from "@/components/shared/Pill"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useVersions, useVersionRelatedReviews } from "@/hooks/api/useVersions"
import { useUrlFilters } from "@/hooks/useUrlFilters"
import FilterChips from "@/components/shared/FilterChips"
import {
  BASELINE_APP, COMPETITORS,
  ENTITY_TYPE_DISPLAY, REVIEW_LABEL_DISPLAY,
} from "@/types/domain"
import type { AppVersion, VersionType } from "@/types/api"
import { ChevronDown, ChevronRight, Star } from "lucide-react"

const VERSION_TYPE_DISPLAY: Record<VersionType, { label: string; variant: "green" | "amber" | "blue" | "gray" | "purple" }> = {
  feature:      { label: "新功能",   variant: "green" },
  bugfix:       { label: "Bug 修复", variant: "gray" },
  localization: { label: "本地化",   variant: "blue" },
  performance: { label: "性能优化", variant: "amber" },
  other:        { label: "其他",     variant: "purple" },
}

export default function Releases() {
  const { value, setValue } = useUrlFilters({ since: "30d", competitor: "" })
  const since = value("since")
  const competitor = value("competitor")

  const { data, isLoading, isError, refetch } = useVersions({
    competitor: competitor || undefined,
    since,
    limit: 200,
  })
  const versions = useMemo(() => data?.versions || [], [data])

  // 排序：is_significant=true 先；同级按 released_at desc（后端已经按这逻辑排了，这里 useMemo 仅为防御）
  const sorted = useMemo(() => {
    return [...versions].sort((a, b) => {
      const sa = a.is_significant ? 1 : 0
      const sb = b.is_significant ? 1 : 0
      if (sa !== sb) return sb - sa
      return (b.released_at || "").localeCompare(a.released_at || "")
    })
  }, [versions])

  const significant = useMemo(() => sorted.filter((v) => v.is_significant), [sorted])
  const others = useMemo(() => sorted.filter((v) => !v.is_significant), [sorted])

  const kpi = useMemo(() => {
    const apps = new Set(versions.map((v) => v.competitor))
    const featureCount = versions.filter((v) => v.version_type === "feature").length
    const localizationCount = versions.filter((v) => v.version_type === "localization").length
    return {
      total: versions.length,
      apps: apps.size,
      feature: featureCount,
      localization: localizationCount,
    }
  }, [versions])

  return (
    <div>
      <PageHeader
        title="产品动态"
        subtitle="每个版本改了什么 + 用户怎么反应 · ⭐ 重要更新置顶（含新功能 / 本地化 / 重大改版）"
        right={
          <span className="text-xs text-muted-foreground tabular-nums">
            {versions.length} 个版本 · ⭐ {significant.length}
          </span>
        }
      />

      <KpiRow>
        <KpiCard label="发版数" value={kpi.total} hint={`近 ${since}`} />
        <KpiCard label="涉及竞品" value={kpi.apps} />
        <KpiCard label="新功能" value={kpi.feature} hint="version_type=feature" />
        <KpiCard label="本地化" value={kpi.localization} hint="新语言 / 区域支持" />
      </KpiRow>

      <div className="space-y-2 mb-3">
        <FilterChips
          label="时间"
          options={[
            { value: "7d",  label: "7d" },
            { value: "14d", label: "14d" },
            { value: "30d", label: "30d" },
            { value: "90d", label: "90d" },
          ]}
          value={since}
          onChange={(v) => setValue("since", v)}
        />
        <FilterChips
          label="竞品"
          options={[
            { value: "", label: "全部" },
            ...COMPETITORS.map((c) => ({ value: c, label: c })),
            { value: BASELINE_APP, label: BASELINE_APP },
          ]}
          value={competitor}
          onChange={(v) => setValue("competitor", v)}
        />
      </div>

      {isLoading && <SkeletonTable rows={4} />}
      {isError && <EmptyState type="error" onRetry={() => refetch()} />}
      {!isLoading && !isError && versions.length === 0 && (
        <EmptyState type="empty" hint="近窗口内无版本变更（app_versions 表可能未抓取）" />
      )}

      {significant.length > 0 && (
        <section className="mb-4">
          <div className="flex items-center gap-2 px-1 mb-2 text-2xs uppercase tracking-wider text-semantic-warning">
            <Star className="w-3 h-3 fill-semantic-warning text-semantic-warning" />
            重要更新 ({significant.length})
          </div>
          <div className="space-y-2">
            {significant.map((v) => <VersionCard key={v.id} v={v} highlight />)}
          </div>
        </section>
      )}

      {others.length > 0 && (
        <section>
          {significant.length > 0 && (
            <div className="px-1 mb-2 text-2xs uppercase tracking-wider text-muted-foreground">
              其他更新 ({others.length})
            </div>
          )}
          <div className="space-y-2">
            {others.map((v) => <VersionCard key={v.id} v={v} />)}
          </div>
        </section>
      )}
    </div>
  )
}

// ─────────── 版本卡 ───────────

function VersionCard({ v, highlight }: { v: AppVersion; highlight?: boolean }) {
  const [open, setOpen] = useState(false)
  const isBaseline = v.competitor === BASELINE_APP
  const notesZh = v.release_notes_zh
  const notesRaw = v.release_notes
  const dateStr = v.released_at
    ? new Date(v.released_at).toLocaleDateString("zh-CN", { month: "short", day: "numeric" })
    : "—"
  const typeMeta = v.version_type ? VERSION_TYPE_DISPLAY[v.version_type] : null

  return (
    <article className={
      "border rounded-md bg-card overflow-hidden " +
      (highlight ? "border-semantic-warning/40" : "border-border-soft")
    }>
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full px-3 py-2 text-left hover:bg-muted/30 transition-colors duration-150"
      >
        {/* 第一行：基本信息 */}
        <div className="flex items-center gap-2 flex-wrap">
          {open ? <ChevronDown className="w-4 h-4 shrink-0" /> : <ChevronRight className="w-4 h-4 shrink-0" />}
          <span className="text-sm font-medium">{v.competitor}</span>
          {isBaseline && <Pill variant="blue">baseline</Pill>}
          <span className="text-xs font-mono text-muted-foreground">{v.version}</span>
          <Pill variant="gray" className="font-mono">{v.platform.toUpperCase()}</Pill>
          {typeMeta && <Pill variant={typeMeta.variant}>{typeMeta.label}</Pill>}
          {highlight && (
            <Star className="w-3 h-3 fill-semantic-warning text-semantic-warning shrink-0" />
          )}
          <span className="ml-auto text-2xs text-muted-foreground tabular-nums shrink-0">
            {dateStr}
          </span>
        </div>

        {/* 第二行：key_changes 中文亮点（卡头直接展示，不需展开） */}
        {(v.key_changes || []).length > 0 && (
          <div className="mt-1.5 ml-6 flex flex-wrap gap-1">
            {(v.key_changes || []).map((c, i) => (
              <Pill key={i} variant="amber">{c}</Pill>
            ))}
          </div>
        )}
      </button>

      {open && (
        <div className="px-3 pb-3 pt-1 space-y-3 border-t border-border-soft">
          {(notesZh || notesRaw) && (
            <section>
              <div className="text-2xs uppercase tracking-wider text-muted-foreground mb-1">
                更新内容
              </div>
              <pre className="text-xs leading-snug text-foreground whitespace-pre-wrap font-sans bg-muted/30 rounded p-2">
                {notesZh || notesRaw}
              </pre>
              {notesZh && notesRaw && (
                <details className="mt-1 text-2xs text-muted-foreground">
                  <summary className="cursor-pointer">查看原文（{v.release_notes_lang || "auto"}）</summary>
                  <pre className="mt-1 whitespace-pre-wrap font-sans bg-muted/20 rounded p-2">{notesRaw}</pre>
                </details>
              )}
            </section>
          )}

          <RelatedReviewsSection versionId={v.id} />
        </div>
      )}
    </article>
  )
}

function RelatedReviewsSection({ versionId }: { versionId: number }) {
  const { data, isLoading, isError } = useVersionRelatedReviews(versionId)

  if (isLoading) {
    return <div className="text-2xs text-muted-foreground">加载关联评论...</div>
  }
  if (isError || !data) {
    return <div className="text-2xs text-muted-foreground">关联评论加载失败</div>
  }

  const ratingDelta = data.rating_change.delta
  const ratingClass =
    ratingDelta == null ? "text-muted-foreground"
      : ratingDelta > 0 ? "text-semantic-success"
      : ratingDelta < 0 ? "text-semantic-danger"
      : "text-muted-foreground"

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3 text-2xs">
        <span className="text-muted-foreground">关联评论 {data.review_count} 条</span>
        {data.rating_change.before != null && data.rating_change.after != null && (
          <span className="font-mono">
            评分 {data.rating_change.before.toFixed(1)} → {data.rating_change.after.toFixed(1)}
            {ratingDelta != null && (
              <span className={"ml-1 " + ratingClass}>
                ({ratingDelta > 0 ? "+" : ""}{ratingDelta.toFixed(1)})
              </span>
            )}
          </span>
        )}
      </div>

      {Object.keys(data.label_distribution).length > 0 && (
        <div className="flex items-center gap-1 flex-wrap">
          <span className="text-2xs text-muted-foreground">label:</span>
          {Object.entries(data.label_distribution).map(([k, n]) => {
            const meta = REVIEW_LABEL_DISPLAY[k as keyof typeof REVIEW_LABEL_DISPLAY]
            return (
              <Pill
                key={k}
                variant={(meta?.color.replace("pill-", "") as any) || "gray"}
              >
                {meta?.text || k} · {n}
              </Pill>
            )
          })}
        </div>
      )}

      {data.top_entities.length > 0 && (
        <div>
          <div className="text-2xs uppercase tracking-wider text-muted-foreground mb-1">
            高频实体
          </div>
          <div className="flex items-center gap-1 flex-wrap">
            {data.top_entities.map((e) => {
              const meta = e.entity_type ? ENTITY_TYPE_DISPLAY[e.entity_type] : null
              return (
                <Pill key={e.canonical_id} variant="gray" className="font-mono">
                  {meta?.prefix} {e.primary_name} ({e.count})
                </Pill>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
