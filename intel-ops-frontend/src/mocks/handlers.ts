/**
 * MSW 拦截器 — 仅在 VITE_USE_MOCK=1 时启用
 *
 * 用途：后端没起 / 没数据时也能开发前端 UI
 */
import { http, HttpResponse } from "msw"

const NOW = new Date().toISOString()

export const handlers = [
  http.get("/api/data/dashboard_data", () => {
    return HttpResponse.json({
      _mock: true,
      generated_at: NOW,
      competitors: ["SofaScore", "FlashScore", "OneFootball", "365Scores",
                    "Fotmob", "LiveScore", "AiScore", "BeSoccer", "310Scores"],
      baseline: "AllFootball",
      market: { /* 占位 */ },
      strategy: { /* 占位 */ },
      comments: { /* 占位 */ },
    })
  }),

  http.get("/api/status", () => {
    return HttpResponse.json({
      sources: {
        appstore_rank: { status: "ok", last_success: NOW },
        androidrank: { status: "ok", last_success: NOW },
        comment_fetch: { status: "ok", last_success: NOW },
        reddit: { status: "ok", last_success: NOW },
        twitter: { status: "skip", last_error: "fapi quota" },
        iap_pricing: { status: "ok", last_success: NOW },
        google_news: { status: "ok", last_success: NOW },
        strategy_monitor: { status: "ok", last_success: NOW },
        appmagic: { status: "ok", last_success: NOW },
        fb_adlib: { status: "pending" },
        sensor_tower: { status: "ok", last_success: NOW },
        similarweb_traffic: { status: "ok", last_success: NOW },
        ai_pipeline: { status: "ok", last_success: NOW },
      },
      retry_queue_size: 0,
      failed_ai_jobs: { comment_label: 2 },
      candidates_count: 9,
      alerts_new_7d: 17,
      ts: NOW,
    })
  }),

  http.get("/api/alerts", () => {
    return HttpResponse.json({
      alerts: [
        {
          id: 1, alert_type: "ranking", severity: "high",
          app_name: "Sofascore", competitor_id: 1,
          metadata: { region: "us", old_rank: 14, new_rank: 6, change: 8 },
          title: "Sofascore 美国体育榜 #14 → #6 · 24h 内 ↑ 8 名",
          rule_triggered: "rank_delta_5plus_24h",
          fired_at: NOW, status: "new",
        },
      ],
      count: 1,
    })
  }),

  http.get("/api/candidates", () => {
    return HttpResponse.json({
      candidates: [
        {
          id: 1, app_id: "1465717844", platform: "ios", bundle_id: "com.bet365.bet365NJ",
          name: "bet365 - Sportsbook & Casino", publisher: "bet365",
          category: "Sports", description_excerpt: "Bet on football, basketball...",
          matched_keywords: ["sports", "betting"],
          is_relevant: true, topic: "multi_sport",
          categories: ["betting", "video", "score"],
          confidence: 0.97, rejection_reason: null,
          classified_at: NOW,
        },
      ],
      count: 1,
    })
  }),
]
