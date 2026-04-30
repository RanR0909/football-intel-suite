/**
 * 业务领域常量 / 显示元数据
 */

import type { AlertType, ReviewLabel, EntityType, Topic, Category } from "./api"

export const COMPETITORS = [
  "SofaScore", "FlashScore", "OneFootball", "365Scores", "Fotmob",
  "LiveScore", "AiScore", "BeSoccer", "310Scores",
] as const

export const BASELINE_APP = "AllFootball" as const
export type CompetitorName = (typeof COMPETITORS)[number] | typeof BASELINE_APP

export const REGIONS = [
  "us", "gb", "de", "fr", "es", "it",
  "br", "mx", "ng", "sa", "ae", "jp",
] as const

export type Region = (typeof REGIONS)[number]

export const REGION_LABELS: Record<Region, string> = {
  us: "美国 🇺🇸",
  gb: "英国 🇬🇧",
  de: "德国 🇩🇪",
  fr: "法国 🇫🇷",
  es: "西班牙 🇪🇸",
  it: "意大利 🇮🇹",
  br: "巴西 🇧🇷",
  mx: "墨西哥 🇲🇽",
  ng: "尼日利亚 🇳🇬",
  sa: "沙特 🇸🇦",
  ae: "阿联酋 🇦🇪",
  jp: "日本 🇯🇵",
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
