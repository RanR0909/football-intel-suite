import DigestCard from "@/components/shared/DigestCard"
import { useCommunity } from "@/hooks/api/useCommunity"
import { Skeleton } from "@/components/shared/Skeleton"
import { ArrowUp, MessageCircle } from "lucide-react"

/** 总览·社媒评论 — 2 条 Reddit 高热帖 */
export default function SocialCard() {
  const { data, isLoading } = useCommunity({ source: "reddit", limit: 2 })
  const rows = data?.posts || []
  const meta = data ? `${data.count} 条最近高热` : "—"

  return (
    <DigestCard title="社媒评论" category="content" detailHref="/content/social" meta={meta}>
      {isLoading && <Skeleton className="h-20" />}
      {!isLoading && rows.length === 0 && (
        <div className="text-xs text-muted-foreground py-3">暂无 Reddit 高热帖</div>
      )}
      {rows.length > 0 && (
        <ul className="space-y-2">
          {rows.map((p) => (
            <li key={p.id} className="text-xs">
              <div className="flex items-baseline gap-1.5 mb-0.5">
                <span className="font-medium truncate">{p.competitor}</span>
                {p.subreddit && (
                  <span className="text-2xs text-muted-foreground font-mono">
                    r/{p.subreddit}
                  </span>
                )}
                <span className="ml-auto inline-flex items-center gap-2 text-2xs text-muted-foreground tabular-nums">
                  {p.score != null && (<span className="inline-flex items-center gap-0.5"><ArrowUp className="w-3 h-3" />{p.score}</span>)}
                  {p.num_comments != null && (<span className="inline-flex items-center gap-0.5"><MessageCircle className="w-3 h-3" />{p.num_comments}</span>)}
                </span>
              </div>
              <a
                href={p.url || "#"}
                target="_blank"
                rel="noreferrer"
                className="line-clamp-2 leading-snug hover:text-brand-700"
              >
                {p.title || p.selftext?.slice(0, 100) || "(无标题)"}
              </a>
            </li>
          ))}
        </ul>
      )}
    </DigestCard>
  )
}
