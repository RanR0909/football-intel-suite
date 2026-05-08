import DigestCard from "@/components/shared/DigestCard"
import { useCommunity } from "@/hooks/api/useCommunity"
import { Skeleton } from "@/components/shared/Skeleton"

function relTime(s: string | null): string {
  if (!s) return ""
  const d = new Date(s)
  if (!Number.isFinite(d.valueOf())) return ""
  const h = Math.floor((Date.now() - d.valueOf()) / 3600_000)
  if (h < 1) return "刚刚"
  if (h < 24) return `${h}h`
  return `${Math.floor(h / 24)}d`
}

/** 总览·社媒评论 — 3 条 Reddit 高热帖 */
export default function SocialCard() {
  const { data, isLoading } = useCommunity({ source: "reddit", limit: 5 })
  const rows = (data?.posts || []).slice(0, 3)

  return (
    <DigestCard title="社媒评论" detailHref="/content/social">
      {isLoading && <Skeleton className="h-20" />}
      {!isLoading && rows.length === 0 && (
        <div className="text-xs text-muted-foreground py-2">暂无 Reddit 高热帖</div>
      )}
      {rows.length > 0 && (
        <ul className="space-y-2">
          {rows.map((p) => {
            const title = p.title_zh || p.title || p.selftext?.slice(0, 100) || "(无标题)"
            return (
              <li key={p.id} className="text-xs">
                <div className="flex items-center gap-1.5 mb-0.5 text-2xs text-muted-foreground font-mono">
                  <span className="font-medium text-foreground font-sans">{p.competitor}</span>
                  {p.subreddit && <span>r/{p.subreddit}</span>}
                  <span className="tabular-nums">
                    ↑{p.score ?? 0}
                    {p.num_comments != null && ` · ${p.num_comments}评`}
                  </span>
                  <span className="ml-auto tabular-nums">{relTime(p.created_utc)}</span>
                </div>
                <a
                  href={p.url || "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="line-clamp-2 leading-snug hover:text-brand-700"
                >
                  {title}
                </a>
              </li>
            )
          })}
        </ul>
      )}
    </DigestCard>
  )
}
