/**
 * 业务领域常量 / 显示元数据
 */

import type {
  AlertType, ReviewLabel, EntityType, Topic, Category,
  BusinessCategory, PostTopic, SellingPoint, AdAudience, AdTone,
} from "./api"

export const COMPETITORS = [
  "SofaScore", "FlashScore", "OneFootball", "365Scores", "Fotmob",
  "LiveScore", "AiScore", "BeSoccer", "310Scores",
] as const

export const BASELINE_APP = "AllFootball" as const
export type CompetitorName = (typeof COMPETITORS)[number] | typeof BASELINE_APP

// 与 data/regions.json 保持一致（项目实际抓取的 12 国 + fb_adlib_de 跑出来的德国）
export const REGIONS = [
  "us", "ng", "my", "id", "sa", "ae",
  "jp", "ca", "vn", "gb", "br", "ru", "de",
] as const

export type Region = (typeof REGIONS)[number]

export const REGION_LABELS: Record<Region, string> = {
  us: "美国 🇺🇸",
  ng: "尼日利亚 🇳🇬",
  my: "马来西亚 🇲🇾",
  id: "印尼 🇮🇩",
  sa: "沙特 🇸🇦",
  ae: "阿联酋 🇦🇪",
  jp: "日本 🇯🇵",
  ca: "加拿大 🇨🇦",
  vn: "越南 🇻🇳",
  gb: "英国 🇬🇧",
  br: "巴西 🇧🇷",
  ru: "俄罗斯 🇷🇺",
  de: "德国 🇩🇪",
}

export const ALERT_TYPE_LABELS: Record<AlertType, string> = {
  ranking: "排名异动",
  commercial: "商业变动",
  news: "商业新闻",
  release: "产品发布",
  rating: "评分变化",
  churn: "流失信号",
  ads: "广告投放",
}

export const REVIEW_LABEL_DISPLAY: Record<ReviewLabel, { text: string; color: string }> = {
  complaint: { text: "问题抱怨", color: "pill-red" },
  feature_request: { text: "功能请求", color: "pill-blue" },
  competitor_compare: { text: "竞品对比", color: "pill-amber" },
  churn_signal: { text: "流失信号", color: "pill-purple" },
  positive: { text: "正向反馈", color: "pill-green" },
  other: { text: "其他", color: "pill-gray" },
}

export const ENTITY_TYPE_DISPLAY: Record<EntityType, { text: string; prefix: string }> = {
  competitor: { text: "竞品", prefix: "@" },
  feature: { text: "功能", prefix: "#" },
  league: { text: "联赛", prefix: "🏆" },
  player: { text: "球员", prefix: "👤" },
  device: { text: "设备", prefix: "📱" },
  bug: { text: "bug", prefix: "🐛" },
  localization: { text: "本地化", prefix: "🌍" },
  payment: { text: "支付", prefix: "💳" },
  language: { text: "语言", prefix: "🗣" },
}

export const TOPIC_LABELS: Record<Topic, string> = {
  football: "足球",
  basketball: "篮球",
  tennis: "网球",
  F1: "F1",
  cricket: "板球",
  multi_sport: "综合体育",
  non_sport: "非体育",
}

export const CATEGORY_LABELS: Record<Category, string> = {
  news: "新闻",
  score: "比分",
  prediction: "预测",
  tipster: "专家推荐",
  betting: "博彩",
  analytics: "数据分析",
  community: "社区",
  video: "视频",
}

export type AppScope = "competitor" | "baseline" | "all"

export const APP_SCOPE_LABELS: Record<AppScope, string> = {
  competitor: "仅竞品",
  baseline: "仅 AF",
  all: "全部",
}

// ─── v2 内容聚合相关 label（task #5/6/7 输出）──────────────────────────

export const BUSINESS_CATEGORY_LABELS: Record<BusinessCategory, string> = {
  funding: "融资 / 投资",
  acquisition: "收购 / 出售",
  partnership: "合作 / 版权",
  launch: "新品 / 新功能",
  strategy: "战略 / 财报",
  hiring: "高管任命",
  legal: "监管 / 诉讼",
  other: "其他",
}

/** spec wireframe 02 的桶分组 — 5 个分桶，覆盖 8 类 category */
export const NEWS_BUCKETS: Array<{
  key: string
  label: string
  variant: "amber" | "teal" | "blue" | "purple" | "gray"
  categories: BusinessCategory[]
}> = [
  { key: "money", label: "融资 / 收购", variant: "amber",
    categories: ["funding", "acquisition"] },
  { key: "deal",  label: "合作 / 联营", variant: "teal",
    categories: ["partnership"] },
  { key: "launch", label: "产品发布", variant: "blue",
    categories: ["launch"] },
  { key: "strategy", label: "战略 / 财报", variant: "purple",
    categories: ["strategy"] },
  { key: "people-legal", label: "人事 / 法律", variant: "gray",
    categories: ["hiring", "legal", "other"] },
]

export const POST_TOPIC_LABELS: Record<PostTopic, string> = {
  player_drama: "球员争议",
  match_result: "比赛结果",
  data_quality: "数据质量",
  app_feature: "App 功能",
  app_bug: "App 问题",
  competitor_compare: "竞品对比",
  industry_news: "行业新闻",
  meme_humor: "梗 / 搞笑",
}

export const SELLING_POINT_LABELS: Record<SellingPoint, string> = {
  live_score: "实时比分",
  local_league: "本地联赛",
  ai_prediction: "AI 预测",
  betting_funnel: "博彩导流",
  data_depth: "数据深度",
  free_app: "强调免费",
  premium_subscription: "Pro / 订阅",
  content_unique: "独家内容",
}

export const AUDIENCE_LABELS: Record<AdAudience, string> = {
  casual_fan: "休闲球迷",
  hardcore_fan: "深度球迷",
  bettor: "博彩用户",
  data_geek: "数据爱好者",
  local_fan: "本地球迷",
}

export const TONE_LABELS: Record<AdTone, string> = {
  urgent: "紧迫型",
  narrative: "叙述型",
  comparative: "对比型",
  numeric: "数字型",
}
