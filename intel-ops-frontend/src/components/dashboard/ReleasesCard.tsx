import DigestCard from "@/components/shared/DigestCard"
import Pill from "@/components/shared/Pill"
import { useVersions } from "@/hooks/api/useVersions"
import { Skeleton } from "@/components/shared/Skeleton"
import type { VersionType } from "@/types/api"
import { BASELINE_APP } from "@/types/domain"

const VERSION_TYPE_DISPLAY: Record<VersionType, { label: string; variant: "green" | "amber" | "blue" | "gray" | "purple" }> = {
  feature:      { label: "新功能",   variant: "green" },
  bugfix:       { label: "Bug 修复", variant: "gray" },
  localization: { label: "本地化",   variant: "blue" },
  performance:  { label: "性能优化", variant: "amber" },
  other:        { label: "其他",     variant: "purple" },
}

function fmtMd(s: string | null | undefined): string {
  if (!s) return ""
  const d = new Date(s)
  if (!Number.isFinite(d.valueOf())) return ""
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

/**
 * 总览·产品动态 — 最近 30d 竞品发版（exclude AF）
 *  · is_significant 优先；版本类型 pill + 版本号 + 日期 + zh release_notes 引用
 */
export default function ReleasesCard() {
  const { data, isLoading } = useVersions({ since: "30d", limit: 30 })
  const all = (data?.versions || []).filter((v) => v.competitor !== BASELINE_APP)

  // 按 is_significant 优先 + released_at 倒序，去同竞品重复，取 3 条
  const sorted = [...all].sort((a, b) => {
    const sigDiff = Number(b.is_significant) - Number(a.is_significant)
    if (sigDiff !== 0) return sigDiff
    return (b.released_at || "").localeCompare(a.released_at || "")
  })
  const seen = new Set<string>()
  const top: typeof all = []
  for (const v of sorted) {
    if (seen.has(v.competitor)) continue
    seen.add(v.competitor)
    top.push(v)
    if (top.length >= 3) break
  }

  return (
    <DigestCard title="产品动态" detailHref="/content/releases">
      {isLoading && <Skeleton className="h-20" />}
      {!isLoading && top.length === 0 && (
        <div className="text-xs text-muted-foreground py-2">30d 内无竞品新版本</div>
      )}
      {top.length > 0 && (
        <ul className="space-y-2">
          {top.map((v) => {
            const typeMeta = v.version_type ? VERSION_TYPE_DISPLAY[v.version_type] : null
            const quote = (v.key_changes && v.key_changes.length > 0)
              ? v.key_changes[0]
              : (v.release_notes_zh || v.release_notes || "").trim().split("\n")[0]
            return (
              <li key={v.id} className="text-xs">
                <div className="flex items-center gap-1.5 mb-0.5">
                  <span className="font-medium truncate">{v.competitor}</span>
                  <span className="font-mono text-2xs text-muted-foreground">{v.version}</span>
                  {typeMeta && <Pill variant={typeMeta.variant}>{typeMeta.label}</Pill>}
                  <span className="ml-auto text-2xs text-muted-foreground font-mono tabular-nums">
                    {fmtMd(v.released_at)}
                  </span>
                </div>
                {quote && (
                  <div className="text-2xs text-muted-foreground pl-2 border-l-2 border-border-soft line-clamp-2 leading-snug">
                    {quote}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </DigestCard>
  )
}
