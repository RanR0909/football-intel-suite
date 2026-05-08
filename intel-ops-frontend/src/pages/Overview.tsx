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
 * 总览看点 — 内容主导（竞品在做什么 / 用户怎么反应）
 *  · 主视图（5 内容卡）：产品动态 / GP 评论 / 社媒评论 / 商业新闻 / 广告投放（双列）
 *  · 副视图（4 数据卡，4 列紧凑）：排名异动 / 收入下载 / IAP 内购 / 网站数据
 *  · 自家 AF 数据不在总览展示（参考 spec：总览以竞品信号为主）
 */
export default function Overview() {
  return (
    <div>
      <PageHeader title="总览看点" />

      <div className="mb-4">
        <SyncStatusBar />
      </div>

      {/* 主视图 · 内容类（5 卡 · 2 列 · AdsCard 占双列） */}
      <section className="mb-5">
        <div className="grid grid-cols-2 gap-3">
          <ReleasesCard />
          <GPReviewsCard />
          <SocialCard />
          <NewsCard />
          <AdsCard />
        </div>
      </section>

      {/* 副视图 · 数据类（4 卡 · 4 列 · 紧凑；无数据时折叠成单行） */}
      <section>
        <div className="grid grid-cols-4 gap-3">
          <RankingsCard />
          <RevenueCard />
          <IapCard />
          <WebsiteCard />
        </div>
      </section>
    </div>
  )
}
