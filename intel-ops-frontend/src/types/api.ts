/**
 * 后端 REST API 响应类型（v2.0 / 与 main_dashboard/dashboard_server.py 对齐）
 *
 * 参考：docs/BACKEND.md §4 schema + INTEL-OPS_前端实现文档_v2.md §8.1
 */

// ===== /api/status =====
export interface StatusResponse {
  sources: Record<string, {
    last_success?: string
    last_attempt?: string
    last_error?: string
    status?: "ok" | "fail" | "pending" | "skip"
  }>
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
  region_code: string
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
}

export interface RankResponse {
  rankings: RankSnapshot[]
  count: number
}

// ===== /api/news =====
export interface NewsItem {
  competitor: string
  title: string
  link: string
  source: string
  desc: string
  pub_iso: string
  is_biz: boolean
}

export interface NewsResponse {
  news: NewsItem[]
  count: number
}

// ===== /api/ads =====
export interface AdCreative {
  id: number
  competitor: string
  region: string
  ad_id: string | null
  body_text: string | null
  media_url: string | null
  fetched_at: string
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
export interface CommunityPost {
  id: number
  competitor: string
  source: "reddit" | "twitter"
  post_id: string
  subreddit: string | null
  title: string | null
  selftext: string | null
  score: number | null
  num_comments: number | null
  url: string | null
  created_utc: string | null
  fetched_at: string
}

export interface CommunityResponse {
  posts: CommunityPost[]
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
