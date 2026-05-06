/** 产品动态页（spec 前端实现文档 §9.7 + wireframe 03）
 *
 * 改造点 vs v1:
 *  · 数据源：app_versions 表（iTunes Lookup → /api/versions），不再用 alerts
 *  · 每条版本一张卡片：release_notes 中文翻译 + 评分变化 + 高频实体 Top
 *  · 点击卡片展开 → 异步拉 /api/versions/:id/related-reviews
 *  · 高频实体 chip 来自 comment_entities（按版本聚合）
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
import type { AppVersion } from "@/types/api"
import { ChevronDown, ChevronRight } from "lucide-react"

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

  const kpi = useMemo(() => {
    const apps = new Set(versions.map((v) => v.competitor))
    const localized = versions.filter((v) =>
      (v.release_notes || "").match(/local|spanish|arabic|japanese|french|portuguese|本地化|语言|翻译/i)
    ).length
    const featured = versions.filter((v) =>
      (v.release_notes || "").match(/new|added|feature|introduc|新增|上线|新功能/i)
    ).length
    return { total: versions.length, apps: apps.size, localized, featured }
  }, [versions])

  return (
    <div>
      <PageHeader
        title="产品动态"
        subtitle="每个版本改了什么 + 用户怎么反应"
        right={
          <span className="text-xs text-muted-foreground tabular-nums">
            {versions.length} 个版本
          </span>
        }
      />

      <KpiRow>
        <KpiCard label="发版数" value={kpi.total} hint={`近 ${since}`} />
        <KpiCard label="涉及竞品" value={kpi.apps} />
        <KpiCard label="含本地化" value={kpi.localized} hint="release notes 提及" />
        <KpiCard label="含新功能" value={kpi.featured} hint="release notes 提及" />
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

      {versions.length > 0 && (
        <div className="space-y-2">
          {versions.map((v) => (
            <VersionCard key={v.id} v={v} />
          ))}
        </div>
      )}
    </div>
  )
}

// ─────────── 版本卡 ───────────

function VersionCard({ v }: { v: AppVersion }) {
  const [open, setOpen] = useState(false)
  const isBaseline = v.competitor === BASELINE_APP
  const notesZh = v.release_notes_zh
  const notesRaw = v.release_notes
  const dateStr = v.released_at
    ? new Date(v.released_at).toLocaleDateString("zh-CN", { month: "short", day: "numeric" })
    : "—"

  return (
    <article className="border border-border-soft rounded-md bg-card overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 h-10 text-left hover:bg-muted/30 transition-colors duration-150"
      >
        {open ? <ChevronDown className="w-4 h-4 shrink-0" /> : <ChevronRight className="w-4 h-4 shrink-0" />}
        <span className="text-sm font-medium">
          {v.competitor}
          {isBaseline && (
            <Pill variant="blue" className="ml-2">baseline</Pill>
          )}
        </span>
        <span className="text-xs font-mono text-muted-foreground">{v.version}</span>
        <Pill variant="gray" className="font-mono">{v.platform.toUpperCase()}</Pill>
        <span className="ml-auto text-2xs text-muted-foreground tabular-nums">
          {dateStr}
        </span>
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
