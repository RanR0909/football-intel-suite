import DigestCard from "@/components/shared/DigestCard"
import { useNews } from "@/hooks/api/useNews"
import { Skeleton } from "@/components/shared/Skeleton"
import { BUSINESS_CATEGORY_LABELS } from "@/types/domain"

function fmtMd(s: string | null | undefined): string {
  if (!s) return ""
  const d = new Date(s)
  if (!Number.isFinite(d.valueOf())) return ""
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

function hostOf(url: string | null): string {
  if (!url) return ""
  try { return new URL(url).hostname.replace(/^www\./, "") } catch { return "" }
}

/** 总览·商业新闻 — 3 条最新商业事件 */
export default function NewsCard() {
  const { data, isLoading } = useNews({ since: "30d", limit: 10 })
  const top = (data?.news || []).slice(0, 3)

  return (
    <DigestCard title="商业新闻" detailHref="/content/news">
      {isLoading && <Skeleton className="h-20" />}
      {!isLoading && top.length === 0 && (
        <div className="text-xs text-muted-foreground py-2">7d 内无商业新闻</div>
      )}
      {top.length > 0 && (
        <ul className="space-y-2">
          {top.map((n) => (
            <li key={n.id} className="text-xs">
              <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
                {n.app_name && <span className="font-medium">{n.app_name}</span>}
                {n.business_category && (
                  <span className="text-2xs text-pill-amber-fg bg-pill-amber-bg px-1 rounded font-mono">
                    {BUSINESS_CATEGORY_LABELS[n.business_category]}
                  </span>
                )}
                <span className="text-2xs text-muted-foreground font-mono">{hostOf(n.url)}</span>
                <span className="ml-auto text-2xs text-muted-foreground font-mono tabular-nums">
                  {fmtMd(n.published_at || n.fetched_at)}
                </span>
              </div>
              <a
                href={n.url}
                target="_blank"
                rel="noreferrer"
                className="line-clamp-2 leading-snug hover:text-brand-700"
              >
                {n.title}
              </a>
            </li>
          ))}
        </ul>
      )}
    </DigestCard>
  )
}
