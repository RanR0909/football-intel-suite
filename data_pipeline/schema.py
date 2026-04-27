"""统一数据 schema。

dashboard 消费的唯一产物是 data/dashboard_data.json，结构由本文件定义。
所有可空字段统一用 None；缺失列表用 []；缺失 dict 用 {}。

设计原则：
- competitor-first 主索引（competitors[<name>]）覆盖详情页
- views.* 切片索引（by_region / by_label / timeline）覆盖跨竞品视角
- alerts / feed / metrics 在聚合阶段预生成，dashboard 渲染零分支
"""

from dataclasses import dataclass, field, asdict
from typing import Optional


# ---------------------------------------------------------------------------
# 竞品维度
# ---------------------------------------------------------------------------

@dataclass
class RankInfo:
    current: Optional[int] = None
    delta_dod: Optional[int] = None         # day-over-day（来自 market_rank.delta）
    delta_wow: Optional[int] = None         # week-over-week（聚合层从 ranking_history 计算）
    history: dict = field(default_factory=dict)   # {YYYY-MM-DD: rank}
    fast_mover: bool = False
    is_new_contender: bool = False
    app_id: Optional[str] = None


@dataclass
class VersionInfo:
    current: Optional[str] = None
    release_notes: Optional[str] = None
    release_date: Optional[str] = None                  # ISO date：来自 iTunes currentVersionReleaseDate
    has_changed: bool = False
    version_changed: bool = False
    is_first_record: bool = False
    changes: list = field(default_factory=list)
    in_app_purchases: list = field(default_factory=list)
    change_type: Optional[str] = None                   # feature / bugfix / pricing / localization
    change_tags: list = field(default_factory=list)     # 全部命中类型（一条更新可同时 feature + localization）
    ai_analysis: Optional[str] = None
    error: Optional[str] = None


@dataclass
class CommentInfo:
    total: int = 0
    negative: int = 0
    labels: dict = field(default_factory=dict)        # 跨地区合并的 {标签: 总数}
    by_region: dict = field(default_factory=dict)     # {region_code: {label, count, negative_count, labels, summary, reviews}}
    weekly_summary: Optional[str] = None              # 来自 weekly_review.json
    deep_analysis: Optional[str] = None               # 来自 competitor_detail_*.json 的 feature_analysis.summary
    feature_keywords: dict = field(default_factory=dict)


@dataclass
class CommunityRaw:
    """Reddit / X 等社媒的原始数据切片（多平台融合），不含 AI 分析。"""
    mention_count: int = 0
    total_engagement: int = 0                          # sum(score + num_comments + shares)
    hot_posts: list = field(default_factory=list)     # top N by score
    recent_comments: list = field(default_factory=list)
    subreddit_distribution: dict = field(default_factory=dict)
    daily_trend: list = field(default_factory=list)   # [{date, posts, comments}]
    date_range_days: int = 7
    # PRD v2 新增字段
    platform_breakdown: dict = field(default_factory=dict)        # {reddit: {mentions, engagement}, twitter: {...}}
    sentiment_daily: list = field(default_factory=list)            # [{date, positive, neutral, negative}]
    pain_points: list = field(default_factory=list)                # [{topic, count, severity, sample_quote}]
    opportunity_signals: list = field(default_factory=list)        # [{theme, count, sample_quote}]
    top_authors: list = field(default_factory=list)                # [{author, post_count, total_score}]


@dataclass
class CommunityAI:
    """AI 分析结果，独立持久化避免被 aggregator 覆盖丢失。"""
    overall_summary: Optional[str] = None
    sentiment: dict = field(default_factory=dict)              # {positive, neutral, negative} 比例
    top_topics: list = field(default_factory=list)
    pain_points: list = field(default_factory=list)
    opportunities: list = field(default_factory=list)
    competitor_mentions: list = field(default_factory=list)
    representative_quotes: list = field(default_factory=list)
    alert_level: str = "low"                           # low / medium / high
    generated_at: Optional[str] = None
    date_range_days: Optional[int] = None
    sample_size: Optional[int] = None
    # PRD v2 新增
    pain_points_with_severity: list = field(default_factory=list)   # [{topic, severity 1-5, frequency, sample}]
    opportunity_matrix: list = field(default_factory=list)          # [{theme, impact 1-5, effort 1-5, sample}]
    cross_competitor_signals: list = field(default_factory=list)    # 跨竞品对比的高频信号


@dataclass
class CommunityInfo:
    raw: CommunityRaw = field(default_factory=CommunityRaw)
    ai_analysis: Optional[CommunityAI] = None


@dataclass
class AdCreative:
    """单条代表性广告（Phase 2）。供 UI 卡片网格直接展示。"""
    ad_id: str = ""
    body_text: str = ""                                     # 文案（截断 500 字）
    media_url: Optional[str] = None
    country: Optional[str] = None
    days_running: int = 0                                   # 持续投放天数（已验证素材的代理）
    start_date: Optional[str] = None
    themes: list = field(default_factory=list)              # 命中的主题标签


@dataclass
class AdsInfo:
    """Meta Ad Library 投放分析。

    - Phase 1：active_count / new_ads / trend / by_country / daily_trend（仅统计）
    - Phase 2：top_themes / user_segments / creative_patterns / top_creatives / creative_diversity（关键词字典）
    - Phase 3：ai_analysis（独立持久化于 data/ads_ai_analysis.json）
    """
    # Phase 1
    active_count: int = 0
    new_ads: int = 0
    trend: str = "stable"
    trend_pct: float = 0.0
    by_country: dict = field(default_factory=dict)
    daily_trend: list = field(default_factory=list)
    last_updated: Optional[str] = None
    # Phase 2
    top_themes: list = field(default_factory=list)          # [{theme, count, samples}]
    user_segments: list = field(default_factory=list)       # [{segment, count, signal_strength}]
    creative_patterns: list = field(default_factory=list)   # [{pattern, count}]
    creative_diversity: float = 0.0                         # 唯一文案数 / 总文案数
    top_creatives: list = field(default_factory=list)       # [AdCreative]
    # Phase 3
    ai_analysis: Optional[dict] = None


@dataclass
class CommercialInfo:
    monetization_tags: list = field(default_factory=list)
    iap_items: list = field(default_factory=list)
    price_alerts: list = field(default_factory=list)
    iap_changes: list = field(default_factory=list)
    rpd_index: Optional[float] = None
    rank: Optional[int] = None
    betting_signals: bool = False
    description_keywords: list = field(default_factory=list)
    seller_url: Optional[str] = None
    ai_intent: Optional[str] = None
    ads: AdsInfo = field(default_factory=AdsInfo)


@dataclass
class CompetitorSnapshot:
    id: str                                  # 与 name 相同，保留以便未来切换
    name: str
    color: str = "#7b6ef6"
    ios_id: Optional[str] = None
    android_id: Optional[str] = None
    rank: RankInfo = field(default_factory=RankInfo)
    version: VersionInfo = field(default_factory=VersionInfo)
    comments: CommentInfo = field(default_factory=CommentInfo)
    commercial: CommercialInfo = field(default_factory=CommercialInfo)
    community: CommunityInfo = field(default_factory=CommunityInfo)


# ---------------------------------------------------------------------------
# 预警 / Feed / Timeline
# ---------------------------------------------------------------------------

@dataclass
class Alert:
    type: str            # negative_review / rank_rise / version_update / commercial_change
    severity: str        # danger / warn / info
    severity_label: str
    icon: str
    title: str
    desc: str
    time: str
    competitor: str
    payload: dict = field(default_factory=dict)


@dataclass
class FeedItem:
    competitor: str
    type: str            # feature / bug / rank / update
    text: str
    time: str
    version: str = ""
    payload: dict = field(default_factory=dict)


@dataclass
class TimelineEvent:
    ts: str              # ISO timestamp
    competitor: str
    event_type: str      # version_change / negative_review / price_alert / rank_rise / iap_change
    title: str
    payload: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 切片 / 周报 / 顶部指标
# ---------------------------------------------------------------------------

@dataclass
class Views:
    """跨竞品的视角切片，UI 想换视角时直接读对应字段。"""
    by_region: dict = field(default_factory=dict)
    # {region_code: {"label": str, "competitors": [{name, count, negative, labels}]}}

    by_label: dict = field(default_factory=dict)
    # {"[问题抱怨]": [{competitor, region, count}]}

    timeline: list = field(default_factory=list)
    # 按 ts 倒序的 TimelineEvent 列表


@dataclass
class ReviewItem:
    """扁平评论条目，前端 page-reviews 直接消费。"""
    competitor: str
    region: str = ""                                    # us / gb / jp
    region_label: str = ""                              # 美国 / 英国 / 日本
    platform: str = "App Store"                         # App Store / Google Play / 未知
    rating: int = 0                                     # 1-5
    version: str = ""
    content: str = ""
    label: str = ""                                     # 原细粒度标签（如 [问题抱怨] / [流失信号]）
    sentiment: str = "neutral"                          # positive / neutral / negative
    date: Optional[str] = None
    source_url: Optional[str] = None                    # 跳回 App Store 评论页


@dataclass
class ReviewAnalysisView:
    """聚合指标 + 扁平 items 列表，供 page-reviews。"""
    metrics: dict = field(default_factory=lambda: {
        "total": 0,
        "sentiment_count": {"positive": 0, "neutral": 0, "negative": 0},
        "topic_count": {},
        "by_competitor": {},
        "top_negative_topics": [],
        "top_positive_topics": [],
    })
    items: list = field(default_factory=list)


@dataclass
class ProductUpdateItem:
    """单条产品动态记录，前端 page-product 时间轴 / 分组视图直接消费。"""
    competitor: str
    version: Optional[str] = None
    date: Optional[str] = None                          # ISO date；缺失时前端用 has_changed 兜底
    type: str = "feature"                               # 主类型
    tags: list = field(default_factory=list)            # 全部命中（feature/bugfix/pricing/localization）
    summary: str = ""                                   # changes 拼接 / release_notes 截断
    source_url: Optional[str] = None                    # App Store 应用页（含 changelog）
    has_changed: bool = False
    is_first_record: bool = False


@dataclass
class ProductUpdatesView:
    """产品动态聚合视图：metrics + 扁平 items 列表（按 date 倒序）。"""
    metrics: dict = field(default_factory=lambda: {
        "week_total": 0, "week_feature": 0,
        "week_bugfix": 0, "week_pricing": 0,
        "week_localization": 0,
    })
    items: list = field(default_factory=list)


@dataclass
class WeeklyData:
    comment: dict = field(default_factory=dict)         # weekly_review.json 原样透传
    commercial: dict = field(default_factory=dict)      # commercial_weekly.json 原样透传


@dataclass
class Metrics:
    changes_detected: int = 0
    max_rank_delta: int = 0
    max_rank_comp: str = ""
    total_negative: int = 0
    monitored: int = 0


@dataclass
class DataFreshness:
    comments: Optional[str] = None
    rank: Optional[str] = None
    strategy: Optional[str] = None
    commercial: Optional[str] = None
    weekly_review: Optional[str] = None
    commercial_weekly: Optional[str] = None


@dataclass
class Meta:
    generated_at: str
    data_freshness: DataFreshness = field(default_factory=DataFreshness)
    schema_version: str = "1.0"


@dataclass
class DashboardData:
    meta: Meta
    competitors: dict           # {name: CompetitorSnapshot}
    views: Views
    alerts: list                # [Alert]
    feed: list                  # [FeedItem]
    leaderboard: list           # 来自 market_rank.leaderboard 原样透传
    new_contenders: list
    fast_movers: list
    weekly: WeeklyData
    metrics: Metrics
    regions: dict = field(default_factory=dict)         # regions.json 透传，UI 渲染地区标签用
    competitor_registry: dict = field(default_factory=dict)  # competitors.json 透传，UI 链接 store 用
    multi_source: dict = field(default_factory=dict)    # market_rank.multi_source 透传（UI 多源数据卡片用）
    baseline: dict = field(default_factory=dict)        # {app, label, comparison} 来自 market_rank
    ai_brief: Optional[str] = None                      # market_rank.ai_brief（榜单 AI 摘要）
    product_updates: ProductUpdatesView = field(default_factory=ProductUpdatesView)
    reviews_analysis: ReviewAnalysisView = field(default_factory=ReviewAnalysisView)
    market_by_country: dict = field(default_factory=dict)  # AppMagic 12 国分榜（v2 替代 iTunes RSS）


def to_dict(obj):
    """递归转 dict，dataclass / list / dict 都能处理。"""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj
