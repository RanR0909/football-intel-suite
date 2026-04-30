import PageHeader from "@/components/shared/PageHeader"
import SyncStatusBar from "@/components/layout/SyncStatusBar"
import DigestCard from "@/components/shared/DigestCard"
import EmptyState from "@/components/shared/EmptyState"
import { useDashboardData } from "@/hooks/api/useDashboardData"

/**
 * 总览看点 — 30 秒扫读 9 个板块
 * 页面 spec：INTEL-OPS_前端实现文档_v2.md §9.1
 *
 * Stage 1 现状：板块卡占位，对接 dashboard_data.json 待 stage 2
 */

export default function Overview() {
  const { data, isLoading, isError, refetch } = useDashboardData()

  return (
    <div>
      <PageHeader
        title="总览看点"
        subtitle="9 个板块今天的关键信号"
      />

      <div className="mb-4">
        <SyncStatusBar />
      </div>

      {isError && <EmptyState type="error" onRetry={refetch} />}

      {/* 数据类（4 卡 · 2×2） */}
      <section className="mb-4">
        <h2 className="text-2xs uppercase tracking-wider text-muted-foreground mb-2">数据类</h2>
        <div className="grid grid-cols-2 gap-3">
          <DigestCard title="排名异动" category="data" detailHref="/data/rankings"
            meta={isLoading ? "加载中…" : "—"}>
            <div className="text-xs text-muted-foreground py-3">板块内容待 stage 2 实现</div>
          </DigestCard>
          <DigestCard title="收入下载" category="data" detailHref="/data/revenue">
            <div className="text-xs text-muted-foreground py-3">板块内容待 stage 2 实现</div>
          </DigestCard>
          <DigestCard title="IAP 内购" category="data" detailHref="/data/iap">
            <div className="text-xs text-muted-foreground py-3">板块内容待 stage 2 实现</div>
          </DigestCard>
          <DigestCard title="网站数据" category="data" detailHref="/data/website">
            <div className="text-xs text-muted-foreground py-3">板块内容待 stage 2 实现</div>
          </DigestCard>
        </div>
      </section>

      {/* 内容类（5 卡 · 2×2 + 1 跨列） */}
      <section>
        <h2 className="text-2xs uppercase tracking-wider text-muted-foreground mb-2">内容类</h2>
        <div className="grid grid-cols-2 gap-3">
          <DigestCard title="产品动态" category="content" detailHref="/content/releases">
            <div className="text-xs text-muted-foreground py-3">板块内容待 stage 2 实现</div>
          </DigestCard>
          <DigestCard title="GP 评论" category="content" detailHref="/content/gp-reviews">
            <div className="text-xs text-muted-foreground py-3">板块内容待 stage 2 实现</div>
          </DigestCard>
          <DigestCard title="社媒评论" category="content" detailHref="/content/social">
            <div className="text-xs text-muted-foreground py-3">板块内容待 stage 2 实现</div>
          </DigestCard>
          <DigestCard title="商业新闻" category="content" detailHref="/content/news">
            <div className="text-xs text-muted-foreground py-3">板块内容待 stage 2 实现</div>
          </DigestCard>
          <DigestCard title="广告投放" category="content" detailHref="/content/ads"
            className="col-span-2">
            <div className="text-xs text-muted-foreground py-3">板块内容待 stage 2 实现（占双列宽）</div>
          </DigestCard>
        </div>
      </section>

      {data && (
        <div className="mt-4 text-2xs text-muted-foreground">
          dashboard_data.json 加载成功 · keys: {Object.keys(data).slice(0, 8).join(", ")}…
        </div>
      )}
    </div>
  )
}
