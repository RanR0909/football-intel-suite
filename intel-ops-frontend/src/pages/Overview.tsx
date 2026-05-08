import PageHeader from "@/components/shared/PageHeader"
import SyncStatusBar from "@/components/layout/SyncStatusBar"
import RankingsCard from "@/components/dashboard/RankingsCard"
import RevenueCard from "@/components/dashboard/RevenueCard"
import IapCard from "@/components/dashboard/IapCard"
import WebsiteCard from "@/components/dashboard/WebsiteCard"
import ReleasesCard from "@/components/dashboard/ReleasesCard"
import GPReviewsCard from "@/components/dashboard/GPReviewsCard"
import SocialCard from "@/components/dashboard/SocialCard"
import NewsCard from "@/components/dashboard/NewsCard"
import AdsCard from "@/components/dashboard/AdsCard"

/**
 * 总览看点 — 30 秒扫读 9 个板块今天有什么
 * 页面 spec：INTEL-OPS_前端实现文档_v2.md §9.1
 */
export default function Overview() {
  return (
    <div>
      <PageHeader title="总览看点" />

      <div className="mb-4">
        <SyncStatusBar />
      </div>

      {/* 数据类（4 卡 · 2×2） */}
      <section className="mb-4">
        <h2 className="text-2xs uppercase tracking-wider text-muted-foreground mb-2">数据类</h2>
        <div className="grid grid-cols-2 gap-3">
          <RankingsCard />
          <RevenueCard />
          <IapCard />
          <WebsiteCard />
        </div>
      </section>

      {/* 内容类（5 卡 · 2×2 + 1 跨双列） */}
      <section>
        <h2 className="text-2xs uppercase tracking-wider text-muted-foreground mb-2">内容类</h2>
        <div className="grid grid-cols-2 gap-3">
          <ReleasesCard />
          <GPReviewsCard />
          <SocialCard />
          <NewsCard />
          <AdsCard />
        </div>
      </section>
    </div>
  )
}
