/**
 * MSW 拦截器 — 仅在 VITE_USE_MOCK=1 时启用
 *
 * 用途：后端没起 / 没数据时也能开发前端 UI
 */
import { http, HttpResponse } from "msw"

const NOW = new Date().toISOString()
const NOW_MIN_5 = new Date(Date.now() - 5 * 60 * 1000).toISOString()
const NOW_MIN_30 = new Date(Date.now() - 30 * 60 * 1000).toISOString()
const NOW_HOUR_3 = new Date(Date.now() - 3 * 3600 * 1000).toISOString()

export const handlers = [
  // ========= dashboard / status =========
  http.get("/api/data/dashboard_data", () => {
    return HttpResponse.json({
      _mock: true,
      generated_at: NOW,
      competitors: ["SofaScore", "FlashScore", "OneFootball", "365Scores",
                    "Fotmob", "LiveScore", "AiScore", "BeSoccer", "310Scores"],
      baseline: "AllFootball",
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

  // ========= alerts =========
  http.get("/api/alerts", () => {
    return HttpResponse.json({
      alerts: [
        {
          id: 1, alert_type: "ranking", severity: "high",
          app_name: "Sofascore", competitor_id: 1,
          metadata: { region: "us", old_rank: 14, new_rank: 6, change: 8 },
          title: "Sofascore 美国体育榜 #14 → #6 · 24h 内 ↑ 8 名",
          rule_triggered: "rank_delta_5plus_24h",
          fired_at: NOW_MIN_5, status: "new",
        },
        {
          id: 2, alert_type: "ranking", severity: "mid",
          app_name: "FlashScore", competitor_id: 2,
          metadata: { region: "br", old_rank: 8, new_rank: 14, change: -6 },
          title: "FlashScore 巴西榜 #8 → #14 · 24h 内 ↓ 6 名",
          rule_triggered: "rank_delta_5plus_24h",
          fired_at: NOW_MIN_30, status: "new",
        },
        {
          id: 3, alert_type: "release", severity: "low",
          app_name: "OneFootball", competitor_id: 3,
          metadata: { version: "v26.4.2", obs_count: 23 },
          title: "OneFootball v26.4.2 上线 · 7 天内首次出现",
          rule_triggered: "new_version_in_reviews",
          fired_at: NOW_HOUR_3, status: "ack",
        },
      ],
      count: 3,
    })
  }),
  http.post("/api/alerts/:id/ack", () => HttpResponse.json({ ok: true })),

  // ========= rank =========
  http.get("/api/rank", () => {
    return HttpResponse.json({
      rankings: [
        { id: 1, source: "sensor_tower", region_code: "us",
          competitor: "AllFootball", name: "All Football", rank_value: 8,
          delta: 2, downloads_num: 3200000, revenue_num: 850000,
          snapshot_date: "2026-04-30", fetched_at: NOW },
        { id: 2, source: "sensor_tower", region_code: "us",
          competitor: "SofaScore", name: "Sofascore", rank_value: 6,
          delta: -2, downloads_num: 5400000, revenue_num: 1200000,
          snapshot_date: "2026-04-30", fetched_at: NOW },
        { id: 3, source: "sensor_tower", region_code: "us",
          competitor: "FlashScore", name: "FlashScore", rank_value: 14,
          delta: 6, downloads_num: 4100000, revenue_num: 950000,
          snapshot_date: "2026-04-30", fetched_at: NOW },
      ],
      count: 3,
    })
  }),

  // ========= reviews =========
  http.get("/api/reviews", () => {
    return HttpResponse.json({
      reviews: [
        { id: 1, competitor: "SofaScore", region_code: "es", platform: "gp",
          score: 2, version: "v26.4.1",
          content: "Esta app es lenta cuando intento ver el Real Madrid live",
          label: "complaint", language: "es",
          translated_text: "这个 app 在我想看皇马 live 时很慢",
          at: NOW_HOUR_3, labeled_at: NOW_MIN_30 },
        { id: 2, competitor: "FlashScore", region_code: "br", platform: "gp",
          score: 5, version: "v25.10.0",
          content: "Melhor app de futebol do mundo",
          label: "positive", language: "pt",
          translated_text: "全世界最好的足球 app",
          at: NOW_HOUR_3, labeled_at: NOW_MIN_30 },
        { id: 3, competitor: "OneFootball", region_code: "us", platform: "gp",
          score: 3, version: "v26.4.2",
          content: "I wish there was an Apple Watch widget",
          label: "feature_request", language: "en",
          translated_text: "希望加 Apple Watch widget",
          at: NOW_HOUR_3, labeled_at: NOW_MIN_30 },
      ],
      count: 3,
    })
  }),

  // ========= news =========
  http.get("/api/news", () => {
    return HttpResponse.json({
      news: [
        {
          competitor: "SofaScore",
          title: "SofaScore Partners with FIFA for World Cup 2026 Stats",
          link: "https://example.com/sofascore-fifa",
          source: "techcrunch.com", desc: "Live stats integration across 64 matches",
          pub_iso: NOW_HOUR_3, is_biz: true,
        },
      ],
      count: 1,
    })
  }),

  // ========= ads =========
  http.get("/api/ads", () => {
    return HttpResponse.json({
      ads: [
        { id: 1, competitor: "SofaScore", region: "us", ad_id: "abc",
          body_text: "Live football scores. Real-time stats. Free download.",
          media_url: null, fetched_at: NOW },
        { id: 2, competitor: "FlashScore", region: "br", ad_id: "def",
          body_text: "O melhor app de placares ao vivo. Baixe grátis.",
          media_url: null, fetched_at: NOW },
        { id: 3, competitor: "365Scores", region: "us", ad_id: "ghi",
          body_text: "Track every match, every league, every team.",
          media_url: null, fetched_at: NOW },
        { id: 4, competitor: "Fotmob", region: "gb", ad_id: "jkl",
          body_text: "Premier League stats like never before.",
          media_url: null, fetched_at: NOW },
      ],
      count: 4,
    })
  }),

  // ========= iap =========
  http.get("/api/iap", () => HttpResponse.json({ iap_items: [], count: 0 })),

  // ========= website =========
  http.get("/api/website", () => {
    return HttpResponse.json({
      website: [
        {
          id: 1, competitor: "AllFootball", domain: "allfootballapp.com",
          snapshot_month: "2026-04-01",
          monthly_visits: "12.3M", monthly_visits_num: 12300000,
          avg_visit_duration: "00:04:32", avg_visit_duration_sec: 272,
          pages_per_visit: 3.8, bounce_rate: 0.41,
          global_rank: 4825, country_rank: 1832, country_rank_country: "Indonesia",
          category_rank: 67, male_share: 0.78, female_share: 0.22,
          top_countries: [], similar_sites: [],
          fetched_at: NOW,
        },
        {
          id: 2, competitor: "SofaScore", domain: "sofascore.com",
          snapshot_month: "2026-04-01",
          monthly_visits: "80.71M", monthly_visits_num: 80710000,
          avg_visit_duration: "00:06:07", avg_visit_duration_sec: 367,
          pages_per_visit: 4.29, bounce_rate: 0.5254,
          global_rank: 635, country_rank: 298, country_rank_country: "Brazil",
          category_rank: 9, male_share: null, female_share: null,
          top_countries: [], similar_sites: [],
          fetched_at: NOW,
        },
      ],
      count: 2,
    })
  }),

  // ========= community =========
  http.get("/api/community", () => {
    return HttpResponse.json({
      posts: [
        { id: 1, competitor: "SofaScore", source: "reddit", post_id: "abc1",
          subreddit: "soccer",
          title: "Anyone else's Sofascore widget broken on iOS 18?",
          selftext: null, score: 142, num_comments: 38,
          url: "https://reddit.com/r/soccer/abc1",
          created_utc: NOW_HOUR_3, fetched_at: NOW },
        { id: 2, competitor: "Fotmob", source: "reddit", post_id: "abc2",
          subreddit: "PremierLeague",
          title: "Fotmob's xG stats are way more accurate than competitors",
          selftext: null, score: 87, num_comments: 22,
          url: "https://reddit.com/r/PL/abc2",
          created_utc: NOW_HOUR_3, fetched_at: NOW },
      ],
      count: 2,
    })
  }),

  // ========= failed-ai-jobs =========
  http.get("/api/failed-ai-jobs", () => {
    return HttpResponse.json({
      jobs: [
        { id: 1, task_name: "comment_label", payload: { review_id: 999, raw_text: "App is bad" },
          error_msg: "JSON decode error: Expecting value: line 1 column 1 (char 0)",
          error_kind: "json_parse", attempts: 2,
          first_failed_at: NOW_HOUR_3, last_attempt_at: NOW_MIN_30, resolved_at: null },
        { id: 2, task_name: "entity_extract", payload: { review_id: 1024 },
          error_msg: "HTTPError 503 from flashapi.top",
          error_kind: "http", attempts: 3,
          first_failed_at: NOW_HOUR_3, last_attempt_at: NOW_MIN_30, resolved_at: null },
      ],
      count: 2,
    })
  }),
  http.post("/api/failed-ai-jobs/:id/retry", () => HttpResponse.json({ ok: true, note: "重置标记，待 ai_pipeline 下次重跑" })),

  // ========= sync-log =========
  http.get("/api/sync-log", () => {
    return HttpResponse.json({
      logs: [
        { id: 1, script: "appstore_rank", label: "App Store 体育榜", competitor: null,
          started_at: NOW_MIN_5, finished_at: NOW_MIN_5, duration_sec: 12.3,
          success: true, error_kind: null,
          stdout_tail: "wrote 100 rank rows to MySQL", stderr_tail: null,
          cmd: "python3 -m async_crawler --sources appstore_rank" },
        { id: 2, script: "twitter", label: "X (Twitter)", competitor: null,
          started_at: NOW_MIN_30, finished_at: NOW_MIN_30, duration_sec: 0.8,
          success: false, error_kind: "auth_failed",
          stdout_tail: null,
          stderr_tail: "fapi.uk returned 'You have made too many requests'",
          cmd: "python3 -m async_crawler --sources twitter" },
      ],
      count: 2,
    })
  }),

  // ========= candidates =========
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
