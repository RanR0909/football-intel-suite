/**
 * 后端 REST API 响应类型（v2.0 / 与 main_dashboard/dashboard_server.py 对齐）
 *
 * 参考：docs/BACKEND.md §4 schema + INTEL-OPS_前端实现文档_v2.md §8.1
 */

// ===== /api/status =====
/** 单个抓取源的运行状态（后端 shared/sync_state.py snapshot 形状 + 派生 status badge） */
export interface SyncSourceState {
  last_success: string | null
  last_attempt: string | null
  last_failure: string | null
  failure_kind: string | null
  failure_msg: string | null
  cookie_status: "ok" | "expired" | "unknown"
  consecutive_failures: number
  /** 后端派生：consecutive_failures>0 → fail；有 last_success → ok；否则 pending */
  status: "ok" | "fail" | "pending"
}

export interface StatusResponse {
  sources: Record<string, SyncSourceState>
  retry_queue_size: number
  failed_ai_jobs: Record<string, number>
  candidates_count: number
  alerts_new_7d: number
  ts: string
}

// ===== /api/alerts =====
export type AlertType = "ranking" | "commercial" | "news" | "release" |
  "rating" | "churn" | "ads"
export type AlertSeverity = "high" | "mid" | "low"
export type AlertStatus = "new" | "ack" | "dismissed"

export interface Alert {
  id: number
  alert_type: AlertType
  severity: AlertSeverity
  app_name: string | null
  competitor_id: number | null
  metadata: Record<string, unknown>
  title: string | null
  rule_triggered: string | null
  fired_at: string
  status: AlertStatus
}

export interface AlertsResponse {
  alerts: Alert[]
  count: number
}

// ===== /api/reviews =====
export type ReviewLabel =
  | "complaint" | "feature_request" | "competitor_compare"
  | "churn_signal" | "positive" | "other"

export type EntityType =
  | "competitor" | "feature" | "league" | "player" | "device"
  | "bug" | "localization" | "payment" | "language"

export interface ReviewEntity {
  canonical_id: string
  type: EntityType
  raw_value: string
}

export interface Review {
  id: number
  competitor: string
  /** 第一个命中的区域（兼容老调用点）；多区域请用 regions */
  region_code: string | null
  /** 经过去重后该评论涉及的所有区域（GP 同一英文评论被 12 国 INSERT 12 次的合并结果） */
  regions: string[]
  platform: "gp" | "ios"
  score: number | null
  version: string | null
  content: string
  label: ReviewLabel | null
  language: string | null
  translated_text: string | null
  at: string | null
  labeled_at: string | null
  entities?: ReviewEntity[]
}

export interface ReviewsResponse {
  reviews: Review[]
  count: number
}

// ===== /api/iap =====
export interface IapItem {
  id: number
  competitor: string
  region_code: string
  name: string
  price: string | null
  price_num: number | null
  currency: string | null
  category: string | null
  fetched_at: string
}

export interface IapResponse {
  iap_items: IapItem[]
  count: number
}

// ===== /api/rank =====
export type RankSource = "appmagic" | "appstore_rank" | "sensor_tower" | "androidrank"

export interface RankSnapshot {
  id: number
  source: RankSource
  /** 'ios' | 'android' — sensor_tower / androidrank 填充；appmagic / appstore_rank 为 null */
  platform: "ios" | "android" | null
  region_code: string | null
  competitor: string | null
  name: string | null
  rank_value: number | null
  delta: number | null
  downloads: string | null
  downloads_num: number | null
  revenue_num: number | null
  snapshot_date: string
  fetched_at: string
  /** 最近一次更早 snapshot 的同 (source, name, platform, region) 的 rank；
   *  通常是昨天的，但跳天兼容；NULL = 没有更早的快照（首次出现） */
  day_ago_rank: number | null
  /** 最近 ≤ 6 天前的同 (source, name, platform, region) 的 rank；NULL = 没有历史数据 */
  week_ago_rank: number | null
  /** 该 app 在本源+区域+平台下首次进库的 snapshot_date（YYYY-MM-DD）。
   *  first_seen_date == snapshot_date 表示今天首次出现 → "今日新上榜"。 */
  first_seen_date: string | null
}

export interface RankResponse {
  rankings: RankSnapshot[]
  count: number
}

// ===== /api/news =====
export type BusinessCategory =
  | "funding" | "acquisition" | "partnership" | "launch"
  | "strategy" | "hiring" | "legal" | "other"

/** v2 schema (news_items 表 + task #5 AI 字段). 旧 NewsItem (link/desc/pub_iso/is_biz)
 *  在 fallback (news_items 表空时读 JSON) 路径下被映射到新 schema 后再返回，
 *  字段对齐：link→url / desc→snippet / pub_iso→published_at / is_biz→is_business。*/
export interface NewsItem {
  id: number
  title: string
  snippet: string | null
  source: string | null
  url: string
  published_at: string | null
  matched_keyword: string | null
  app_name: string | null
  fetched_at: string | null
  /** MySQL TINYINT(1) — 实际通过 JSON 序列化为 0 / 1 / null（不是 boolean）。
   *  前端用 truthy 检查兼容 (`if (n.is_business)`) 即可，别用 `=== true`。 */
  is_business: 0 | 1 | null
  business_category: BusinessCategory | null
  competitors_mentioned: string[]
  classification_confidence: number | null
  classified_at: string | null
}

export interface NewsResponse {
  news: NewsItem[]
  count: number
}

// ===== /api/ads =====
export type SellingPoint =
  | "live_score" | "local_league" | "ai_prediction" | "betting_funnel"
  | "data_depth" | "free_app" | "premium_subscription" | "content_unique"
export type AdAudience =
  | "casual_fan" | "hardcore_fan" | "bettor" | "data_geek" | "local_fan"
export type AdTone = "urgent" | "narrative" | "comparative" | "numeric"

export interface AdCreative {
  id: number
  competitor: string
  region: string
  ad_id: string | null
  body_text: string | null
  media_url: string | null
  start_date: string | null
  platform: string | null
  page_name: string | null
  fetched_at: string
  /** task #7 ad_selling_point 写入，未分类时全为 null/空 */
  selling_points: SellingPoint[]
  audience: AdAudience | null
  tone: AdTone | null
  selling_classified_at: string | null
  selling_confidence: number | null
}

export interface AdsResponse {
  ads: AdCreative[]
  count: number
}

// ===== /api/website =====
export interface WebsiteTraffic {
  id: number
  competitor: string
  domain: string
  snapshot_month: string
  monthly_visits: string | null
  monthly_visits_num: number | null
  avg_visit_duration: string | null
  avg_visit_duration_sec: number | null
  pages_per_visit: number | null
  bounce_rate: number | null
  global_rank: number | null
  country_rank: number | null
  country_rank_country: string | null
  category_rank: number | null
  male_share: number | null
  female_share: number | null
  top_countries: { country: string; share: number }[]
  similar_sites: { domain: string; affinity: number }[]
  fetched_at: string
}

export interface WebsiteResponse {
  website: WebsiteTraffic[]
  count: number
}

// ===== /api/community =====
export type PostTopic =
  | "player_drama" | "match_result" | "data_quality"
  | "app_feature" | "app_bug" | "competitor_compare"
  | "industry_news" | "meme_humor"

export interface CommunityPost {
  id: number
  competitor: string
  source: "reddit" | "twitter"
  post_id: string
  subreddit: string | null
  title: string | null
  /** task 9 post_translate 写入；NULL = 还没翻译过 */
  title_zh: string | null
  selftext: string | null
  /** task 9 post_translate 写入；NULL = 还没翻译过或原 selftext 为空 */
  selftext_zh: string | null
  score: number | null
  num_comments: number | null
  url: string | null
  created_utc: string | null
  fetched_at: string
  translated_at: string | null
  /** task #6 post_topic_classifier 写入 */
  primary_topic: PostTopic | null
  secondary_topics: PostTopic[]
  competitor_mentioned: string | null
  topic_classified_at: string | null
  topic_confidence: number | null
}

export interface CommunityResponse {
  posts: CommunityPost[]
  count: number
}

// ===== /api/versions (NEW) =====
export type VersionType = "feature" | "bugfix" | "localization" | "performance" | "other"

export interface AppVersion {
  id: number
  competitor: string
  platform: "ios" | "gp"
  version: string
  release_notes: string | null
  release_notes_lang: string | null
  release_notes_zh: string | null
  translated_at: string | null
  released_at: string | null
  first_seen_at: string | null
  /** task 11 version_classify 写入；NULL = 还没分类 */
  version_type: VersionType | null
  /** 1-3 个中文短句（≤20 字），卡头亮点展示 */
  key_changes: string[]
  /** 是否值得置顶高亮（feature 通常 true / 纯 bugfix 通常 false） */
  is_significant: boolean | null
  classified_at: string | null
}

export interface VersionsResponse {
  versions: AppVersion[]
  count: number
}

export interface VersionRelatedReviewsResponse {
  version_id: number
  competitor: string
  version: string
  review_count: number
  label_distribution: Partial<Record<ReviewLabel, number>>
  rating_change: {
    before: number | null
    after: number | null
    delta: number | null
  }
  top_entities: Array<{
    canonical_id: string
    primary_name: string
    entity_type: EntityType | null
    count: number
  }>
}

// ===== /api/reviews/aggregated (NEW) =====
export type ReviewsAggregatedTab = "problems" | "praise" | "localization" | "churn"

export interface ReviewsAggregatedItem {
  canonical_id: string
  primary_name: string
  /** 中文翻译（task 8 entity_translate 写入）；NULL = 还没翻译过 */
  chinese_name: string | null
  entity_type: EntityType | null
  total_mentions: number
  by_competitor: Record<string, number>
  by_region: Record<string, number>
  representative_review: {
    id: number
    text_zh: string | null
    competitor: string
    region: string
    score: number | null
  } | null
}

export interface ReviewsAggregatedResponse {
  tab: ReviewsAggregatedTab
  items: ReviewsAggregatedItem[]
  count: number
}

// ===== /api/community-posts/aggregated (NEW) =====
export type CommunityAggregatedDim = "topic" | "player" | "league" | "competitor"

export interface CommunityAggTopicRow {
  topic: PostTopic
  post_count: number
  total_score: number
  comp_count: number
}

export interface CommunityAggCompetitorRow {
  competitor: string
  post_count: number
  total_score: number
  top_topics: Array<{ topic: PostTopic; n: number }>
}

/** dim=player|league — 来自 community_post_entities × entity_aliases (migration 0016) */
export interface CommunityAggEntityRow {
  canonical_id: string
  primary_name: string
  /** 中文翻译（task 8 entity_translate 写入）；NULL = 还没翻译过 */
  chinese_name: string | null
  post_count: number
  total_score: number
  top_competitors: Array<{ competitor: string; n: number }>
  cooccurring: Array<{ name: string; etype: EntityType; n: number }>
}

export interface CommunityAggregatedResponse {
  dim: CommunityAggregatedDim
  items: CommunityAggTopicRow[] | CommunityAggCompetitorRow[] | CommunityAggEntityRow[]
  count: number
  hint?: string
}

// ===== /api/ads/aggregated (NEW) =====
export type AdsAggregatedDim = "selling_point" | "region" | "competitor"

export interface AdsAggSellingRow {
  selling_point: SellingPoint
  creative_count: number
  comp_count: number
  top_competitors: Array<{ competitor: string; n: number }>
}

export interface AdsAggRegionRow {
  region: string
  creative_count: number
  comp_count: number
}

export interface AdsAggCompetitorRow {
  competitor: string
  creative_count: number
  selling_points_breakdown: Array<{ selling_point: SellingPoint; n: number }>
}

export interface AdsAggregatedResponse {
  dim: AdsAggregatedDim
  items: AdsAggSellingRow[] | AdsAggRegionRow[] | AdsAggCompetitorRow[]
  count: number
}

// ===== /api/candidates =====
export type Topic = "football" | "basketball" | "tennis" | "F1" |
  "cricket" | "multi_sport" | "non_sport"
export type Category =
  | "news" | "score" | "prediction" | "tipster"
  | "betting" | "analytics" | "community" | "video"

export interface Candidate {
  id: number
  app_id: string
  platform: "gp" | "ios"
  bundle_id: string | null
  name: string
  publisher: string | null
  category: string | null
  description_excerpt: string | null
  matched_keywords: string[]
  is_relevant: boolean
  topic: Topic
  categories: Category[]
  confidence: number
  rejection_reason: string | null
  classified_at: string
}

export interface CandidatesResponse {
  candidates: Candidate[]
  count: number
}

// ===== /api/failed-ai-jobs =====
export interface FailedAiJob {
  id: number
  task_name: "comment_label" | "entity_extract" | "alert_title" | "app_classifier"
  payload: Record<string, unknown>
  error_msg: string | null
  error_kind: string | null
  attempts: number
  first_failed_at: string
  last_attempt_at: string
  resolved_at: string | null
}

export interface FailedAiJobsResponse {
  jobs: FailedAiJob[]
  count: number
}

// ===== /api/sync-log =====
export interface SyncLogEntry {
  id: number
  script: string
  label: string | null
  competitor: string | null
  started_at: string
  finished_at: string | null
  duration_sec: number | null
  success: boolean
  error_kind: string | null
  stdout_tail: string | null
  stderr_tail: string | null
  cmd: string | null
}

export interface SyncLogResponse {
  logs: SyncLogEntry[]
  count: number
}
