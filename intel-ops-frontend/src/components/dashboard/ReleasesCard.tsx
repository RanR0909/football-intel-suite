import DigestCard from "@/components/shared/DigestCard"
import { useAlerts } from "@/hooks/api/useAlerts"
import { Skeleton } from "@/components/shared/Skeleton"

/** 总览·产品动态 — 最近 7d release 类 alerts（3 条）*/
export default function ReleasesCard() {
  const { data, isLoading } = useAlerts({
    type: "release", since: "7d", limit: 3,
  })
  const top = data?.alerts || []
  const meta = data ? `7d 内 ${data.count} 次发版` : "—"

  return (
    <DigestCard title="产品动态" category="content" detailHref="/content/releases" meta={meta}>
      {isLoading && <Skeleton className="h-16" />}
      {!isLoading && top.length === 0 && (
        <div className="text-xs text-muted-foreground py-3">7d 内无新版本</div>
      )}
      {top.length > 0 && (
        <ul className="space-y-1">
          {top.map((a) => {
            const md = a.metadata as { version?: string; first_seen?: string; obs_count?: number }
            return (
              <li key={a.id} className="text-xs py-1">
                <div className="flex items-baseline gap-2">
                  <span className="font-medium truncate">{a.app_name}</span>
                  <span className="font-mono text-2xs text-muted-foreground tabular-nums">
                    {md.version}
                  </span>
                </div>
                {md.first_seen && (
                  <div className="text-2xs text-muted-foreground mt-0.5">
                    首见 {new Date(md.first_seen).toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" })}
                    {md.obs_count != null && ` · ${md.obs_count} 次观测`}
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
