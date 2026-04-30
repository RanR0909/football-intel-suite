# 数据源

> 9 个 竞品 × 12 个区域，15 个数据源 / 任务。

---

## HTTP 抓取（9 个）

### 1. `appstore_rank` — Apple App Store 体育类免费榜（每日）

**源**：`itunes.apple.com/us/rss/topfreeapplications/genre=6004/limit=100/json`

每次抓 100 个 app，每个：

| 字段 | 含义 | 例 |
|---|---|---|
| rank | 排名（1-100） | 74 |
| name | 应用名 | "Sofascore: Live Sports Scores" |
| app_id | App Store ID | "1176147574" |
| bundle_id | iOS bundle | "com.SofaScore.iOS" |
| category | 类目标签 | "Sports" |

---

### 2. `androidrank` — 累计下载量 + 评分历史（每日）

**源**：`androidrank.org/application/<slug>/<package>` 网页（每个竞品独立 URL）
解析嵌入的 JS 变量：`drawChartRankTotalData` / `drawChartRatingTotalData`

| 字段 | 含义 | 例 |
|---|---|---|
| download_history | 累计下载历史（10 个时间点的 [日期, 累计下载]） | `[["2026-04-05", 1117801], ...]` |
| rating_history | 平均星级历史（同上结构） | `[["2026-04-05", 4.7], ...]` |

8/9 可抓（310Scores 太新没收录）。

---

### 3. `comment_fetch` — Google Play / iOS 用户评论（每日）

**源**：
- Google Play: `google_play_scraper` 库（包装 Google Play 内部 API）
- iOS: `app_store_scraper` 库（**Apple 反爬，多数返 0**）

每个 app × 12 区，每次最多 200 条，过滤过去 3 天的：

| 字段 | 含义 | 例 |
|---|---|---|
| score | 评分 1-5 | 4 |
| version | 用户用的 app 版本 | "26.04.09" |
| content | 评论文本 | "Best app for live football scores!" |
| at | 评论时间 | "2026-04-27T08:32:00" |
| _platform | 来源平台 | "gp" / "ios" |

iOS 当前完全 0（Apple 主动反爬，详见 [config/README.md](../config/README.md)）。

---

### 4. `comment_label` — 用 Claude 给评论打标签（每日，AI 任务）

**输入**：上面 `comment_fetch` 的 raw 评论
**模型**：Claude haiku 4.5
**输出**：每条评论打一个标签

| 标签 | 含义 |
|---|---|
| `[问题抱怨]` | 卡顿 / 闪退 / bug |
| `[高价值功能请求]` | "希望增加..." 这类 |
| `[竞品对比]` | "比 X 好" / "不如 Y" |
| `[流失信号]` | "曾经好，现在差" / "卸了" |
| `[正向反馈]` | 单纯好评 |
| `[其他]` | 不属于上述 |

非英语区先调 Claude 翻译成英文再分类。

---

### 5. `reddit` — Reddit 帖子搜索（每日）

**源**：`reddit.com/search.json?q="<app_name>"&sort=relevance&t=month&limit=30`
带 post-filter：title+selftext 必须真含 app 名（避免假阳性）

每个竞品最多 30 条帖子：

| 字段 | 含义 | 例 |
|---|---|---|
| post_id | Reddit 帖子 ID | "1abc23" |
| subreddit | 所在 subreddit | "soccer" |
| title | 标题 | "FotMob ad spam getting worse" |
| selftext | 正文（最多 2000 字） | "I've been using ..." |
| score | upvote 净值 | 142 |
| num_comments | 评论数 | 23 |
| upvote_ratio | 顶踩比 | 0.95 |
| created_utc | 发布时间戳 | 1714123456 |
| url | 帖子链接 | reddit.com/r/soccer/... |
| comments | 顶热评 20 条（可关）| `[{body, score, created_utc}, ...]` |

---

### 6. `twitter` — X (Twitter) 搜索（每日，经 fapi.uk / utools 转发）

**源**：第三方代理 `https://fapi.uk/api/base/apitools/search`（[文档](https://utools.readme.io/reference/search-2)）
鉴权：`UTOOLS_AUTH_TOKEN` —— 用户自带的 X 网页 cookie `auth_token` 值（不是官方 API key）。

⚠️ **风险提示**：fapi.uk 通过用户 cookie 模拟登录抓取，违反 X ToS，存在小号被封禁的风险。
- 强烈建议配一个**一次性小号**专用 cookie，不要用主号 / 工作号
- cookie 通常 30 天内失效；爬虫检测到 401 会立刻停抓并发飞书告警
- 切回官方 API 的旧实现可在 `git log async_crawler/sources/twitter.py` 中找到

每竞品一次查询（`words="<App>" product=Latest count=30`），输出字段：

| 字段 | 含义 | 例 |
|---|---|---|
| post_id | 推文 ID | "1812345678901234567" |
| text | 推文文本 | "FotMob just dropped AI predictions ..." |
| author | 发推用户名 | "fotmob_official" |
| score | 点赞数 | 42 |
| num_comments | 回复数 | 3 |
| shares_count | 转推数 | 8 |
| created_utc | 发布时间（UTC 时间戳）| 1714291296.0 |
| lang | 语言 | "en" |
| url | 推文链接 | https://twitter.com/fotmob_official/status/1812... |

入库 `community_posts`（dedupe by `(source='twitter', post_id)`），与 reddit 同表。

---

### 7. `iap_pricing` — Apple App Store IAP 价格（每周）

**源**：`apps.apple.com/<region>/app/id<app_id>` 网页 HTML
解析 svelte 渲染的 `<div class="text-pair">` 找 IAP 列表

每个 app × 12 区：

| 字段 | 含义 | 例 |
|---|---|---|
| name | IAP 名 | "Sofascore Analyst (Monthly)" |
| price | 价格原始字符串 | "$24.99" / "￥168" / "€19.99" |
| price_num | 解析后数值 | 24.99 |
| currency | ISO 货币代码 | "USD" / "CNY" / "EUR" |
| category | 分类（统一打 "iap"） | "iap" |

---

### 8. `google_news` — Google News RSS 商业新闻（**每周一 09:00**，免 key）

**源**：`news.google.com/rss/search?q=...&hl=en-US&gl=US&ceid=US:en`（公开 RSS，无 API key 限制）
**配置**：`config/google_news.json`（关键词列表 + block_sources + 9 竞品 + 自家网站排除）

每竞品发 **2 个 query**：
1. **broad**：`"<App>" -site:<own_site> when:7d` — 大范围捞
2. **business**：`"<App>" (funding OR acquires OR raises OR partnership OR ...) -site:<own_site> when:7d` — 命中商业关键词的标 ⭐ 排前

合并去重 → 过滤 17 类 block_sources（社媒 / 招聘站 / 商店 / 自家 alias）→ 排序（biz 优先 → 时间倒序）

每竞品最多 10 条：

| 字段 | 含义 | 例 |
|---|---|---|
| title | 新闻标题 | "OneFootball partners with FIFA for 2026 World Cup" |
| link | 文章 URL | bbc.com/sport/football/... |
| pub | RFC822 发布时间 | "Mon, 28 Apr 2026 14:32:00 GMT" |
| pub_iso | ISO8601 解析后 | "2026-04-28T14:32:00+00:00" |
| source | 来源媒体 | "BBC Sport" |
| desc | 摘要 | "OneFootball, the football media platform..." |
| **is_biz** | 是否命中商业关键词 | true（⭐）/ false |

**block_sources** 17 项（写在 config/google_news.json）：
- 社媒：x.com / twitter.com / instagram.com / facebook.com / tiktok.com / reddit.com / youtube.com / threads.com
- 招聘：Indeed / Startup Jobs / LinkedIn / Built In / BeBee
- 商店：Apple / Google Play / play.google.com
- 杂项：MLSNEXTPro.com / amazonaws.com

---

### 9. `strategy_monitor` — 竞品产品迭代监控（每日，事件驱动）

**源**：iTunes Search API + Lookup API
- `itunes.apple.com/search?term=<app_name>&entity=software&limit=1`
- `itunes.apple.com/lookup?id=<track_id>&entity=software`

每竞品 2 个 GET：

| 字段 | 含义 | 例 |
|---|---|---|
| version | 当前版本号 | "26.04.09" |
| release_notes | 更新日志（多语言混合）| "Fixed crash on iOS 17. Added Spanish localization for La Liga." |
| release_date | 发版日期 | "2026-04-23" |
| in_app_purchases | IAP 状态（API 不返回详细，只标"免费/付费"） | `[]` 或 `[{note: "App 免费下载，可能存在内购"}]` |
| track_name | App Store 显示名 | "Sofascore: Live Sports Scores" |
| track_id | iTunes ID | 1176147574 |
| bundle_id | iOS bundle | "com.SofaScore.iOS" |

跟昨天的快照对比，**仅当版本号 / IAP 状态变了**才触发 AI 分析（4 维度：产品迭代 / 商业策略 / 本地化 / 威胁等级）。

---

##  Playwright 抓取（3 个，需登录浏览器 cookie）

### 10. `appmagic` — AppMagic 全球 + 12 国排名（每日）

**源**：`appmagic.rocks/top-charts/apps?tag=243526`（Sports News tag），全球 + 12 国 = 13 张榜
**登录态**：`~/.appmagic-profile`（免费账号即可）

每张榜 Top 100，共 ~1300 行：

| 字段 | 含义 | 例 |
|---|---|---|
| rank | 排名（1-100） | 1 |
| name | 应用名 | "FotMob - Soccer Live Scores" |
| publisher | 发行商 | "FotMob" |
| delta | 排名变化 | "↑3" / "↓7" / "—" |
| downloads | 下载估算（仅 worldwide 榜带） | "~1M" |
| region | 国家代码 / null=worldwide | "us" / null |

---

### 11. `fb_adlib` — Meta 广告库（每日，5 国 × 9 竞品 = 45 query 拆任务并跑）

**源**：`facebook.com/ads/library/?active_status=active&country=<CC>&q=<app>`
**登录态**：`~/.meta-adlib-profile`（接受 cookie banner 即可，不需要 FB 登录）

每个 query 滚动 2 次扫页面所有 "Library ID:" 卡片：

| 字段 | 含义 | 例 |
|---|---|---|
| ad_id | Library ID（Meta 的广告唯一 ID） | "234567890123456" |
| text | 广告文案 | "Get live scores instantly · Download now" |
| start_date | "Started running on" 文案 | "Apr 1, 2026" |
| platform | 投放平台 | "Facebook · Instagram · Audience Network" |
| page_name | 投放主页名 | "Sofascore" |
| media_url | 创意素材链接（图 / 视频）| `scontent.fbcdn.net/...` |
| country | 投放国家（标注用） | "us" |

---

### 12. `sensor_tower` — Sensor Tower 应用概览（每日）

**源**：`app.sensortower.com/overview/<ios_id>?country=US&os=ios`
**登录态**：`~/.sensortower-profile`（免费账号即可）

每竞品 1 page，9 个：

| 字段 | 含义 | 例 |
|---|---|---|
| downloads | 月下载估算（worldwide） | 200000（"200K"）|
| revenue | 月收入估算（worldwide） | 100000（"$100K"）|
| category_rank | 美国体育类下载排名 | 74 |
| rating | 平均星级 | （免费版可见但目前 DOM 抓不到，待优化）|
| ratings_count | 总评分数 | （同上） |
| raw_text | 整页文本前 4000 字（调试用）| 整段 dashboard 文案 |

**Pro 锁住**：RPD / Avg. DAU / Time Spent / Session Count（页面显示 "Upgrade to access this metric"）。

---

### 13. `similarweb_traffic` — Similarweb 网站流量（每周，免费公开页）

**源**：`similarweb.com/website/<domain>/`（不登录即可看核心字段）
**登录态**：`~/.similarweb-profile` —— 一次性人工过 Cloudflare challenge，profile 持久化后续 headless 运行
**首次配置**：
```bash
python3 -m market_rank.scrape_similarweb login
# 浏览器弹出 → 完成 CF 验证 → 看到 sofascore.com 概览页流量数据 → 关窗口
```

每竞品 1 个 page，9 个（每周日 03:00 跑），数据按"月"对齐（snapshot_month = 当月 1 号）。

⚠️ **Tier 说明**：Similarweb 三档可见数据
- **Anonymous（不登录）**：完全免费 / 永久可用 — 8 个稳定字段
- **Free account（注册账号 + trial 过期）**：anonymous + 关键词 / 部分历史
- **Premium Trial（新账号 8 天）**：全开（含设备 + 6 渠道分布 + similar_sites）

字段一览（按 tier 标稳定性，**永远 NULL-safe** — 缺失自动 null）：

| 字段 | Anonymous | Trial | 长期稳定 | 例 |
|---|:-:|:-:|:-:|---|
| `monthly_visits` / `_num` | ✅ | ✅ | **核心** | `"85M"` / `85000000` |
| `avg_visit_duration` / `_sec` | ✅ | ✅ | **核心** | `"00:06:23"` / `383` |
| `pages_per_visit` | ✅ | ✅ | **核心** | `4.32` |
| `bounce_rate` | ✅ | ✅ | **核心** | `0.3345` |
| `global_rank` | ✅ | ✅ | **核心** | `635` |
| `country_rank` / `_country` | ✅ | ✅ | **核心** | `298` / `"Brazil"` |
| `category_rank` | ✅ | ✅ | **核心** | `4` |
| `top_countries` (JSON, top 5)| ✅ | ✅ | **核心** | `[{country, share}]` |
| `desktop_share` / `mobile_share` | ❌ | ✅ | trial-only | `0.5948` / `0.4052` |
| **6 大流量来源**（小数 0–1） | | | | |
| `direct_share` | ⚠️只此一项 | ✅ | trial-only | `0.5404` |
| `search_share` | ❌ | ✅ | trial-only | `0.2108` |
| `social_share` | ❌ | ✅ | trial-only | `0.1941` |
| `referral_share` | ❌ | ✅ | trial-only | `0.0300` |
| `mail_share` | ❌ | ✅ | trial-only | `0.0106` |
| `display_share` | ❌ | ✅ | trial-only | `0.0030` |
| `top_keywords` (JSON) | ❌（CPC 格式） | ✅ | trial-only | `[{kw, share}]` |
| `male_share` / `female_share` | ✅ | ❌ | anon-only | `0.7641` / `0.2359` |
| `similar_sites` (JSON, top 10) | ✅ | ❌ | anon-only | `[{domain, affinity}]` |
| `raw_text` | ✅ | ✅ | 调试 | 前 8000 字 |

入库 `website_traffic` 表，`UNIQUE (competitor_id, snapshot_month)`，月内重复抓 UPSERT 同一行。
**8 个核心字段在所有 tier 永远稳定**；trial-only 字段在 8 天 trial 过期后 + 你登出 → null（dashboard 显示 `—`）。
**不会强制升级 / 不会因为字段缺失而崩溃**。

CLI：
```bash
python3 -m market_rank.scrape_similarweb              # 正常抓（用 ~/.similarweb-profile）
python3 -m market_rank.scrape_similarweb --domain X   # 只抓一个站
python3 -m market_rank.scrape_similarweb --headed     # 显示浏览器调试
python3 -m market_rank.scrape_similarweb --anonymous --domain X   # 不带 cookie，验证 anon 字段集（不入 MySQL）
python3 -m market_rank.scrape_similarweb login        # 一次性手动过 CF + 登录（profile 持久化）
```

---

##  AI 分析（5 个，不直接抓数据）

### 13. `commercial_strategy` — 商业策略画像（每日）

**输入**：`data/raw/iap_pricing.json` + `data/strategy_monitor.json` + Apple App Store 元数据
**模型**：Claude haiku 4.5
**输出**：

| 字段 | 含义 | 例 |
|---|---|---|
| monetization_tags | 5 类标签（可多选）| `["Subscription Heavy", "Ad-Driven"]` |
| ai_intent | 30 字内一句话商业意图 | "OneFootball 试水订阅制，对标 Apple News+" |
| iap_items | IAP 列表带分类 | `[{name, price_usd, currency, category, price_by_region}]` |
| price_alerts | 价格涨跌 ≥10% 事件 | `[{name: "VIP", direction: "up", prev: "$5", curr: "$7"}]` |
| iap_changes | 新增 / 移除的 IAP 项 | `[{name, type: "新增"}]` |
| rpd_index | 简易付费率（rank ÷ IAP 数量）| 0.123 |
| rank | 当前 App Store 排名 | 74 |
| betting_signals | 关键词检测（odds/bet/wager）| true / false |
| description_keywords | App 描述高频词 | `["live", "scores", "match"]` |
| seller_url | 开发商网站 | "https://sofascore.com" |

---

### 14. weekly 任务组（4 个，周日 03:00 跑）

#### 14a. `weekly_review` — 7 天评论周报

跨 9 竞品 + 12 区，~3000 字 markdown：
- 本周核心发现（趋势 / 痛点 / 高价值请求 / 流失信号）
- 各竞品分析摘要（评分趋势 / Top 抱怨 / Top 请求 / 竞品对比）
- 本地化专题（每地区分别看）
- 跨竞品功能对比

#### 14b. `competitor_detail × 9` — 单竞品深度报告

每个竞品独立报告，~2000 字 markdown：
- 用户抱怨 Top 3
- 高价值功能请求 Top 3
- 竞品对比提及（用户拿它和谁比）
- 忠实用户流失信号
- 3 条可执行产品建议

#### 14c. `commercial_weekly` — 商业策略周报

7 天 IAP 价格变动 + 变现模式演变：
- 价格调整趋势（涨/降/新增）
- 变现模式演变（订阅化 / 广告化 / 博彩导流）
- 2-3 条商业建议

#### 14d. `review_3d` / `ads_strategy` / `community_insights`

dashboard 上的"按需"AI（用户点按钮才跑）：
- review_3d：单竞品 3 天评论摘要（Top 痛点 / 代表原话 / 话题标签）
- ads_strategy：单竞品 Meta 广告投放策略解读（受众画像 / 卖点 / 风险）
- community_insights：单竞品 Reddit 舆情解读（话题分布 / 痛点 / 机会）

---

## 数据流

```
15 个源 → 抓
   ├─ HTTP 抓取（9）：appstore_rank / androidrank / comment_fetch / reddit /
   │                  twitter (fapi.uk) / iap_pricing / google_news /
   │                  strategy_monitor
   ├─ Playwright（4）：appmagic / fb_adlib / sensor_tower / similarweb_traffic
   └─ AI 分析（5）：comment_label / commercial_strategy / weekly_review /
                   competitor_detail × 9 / commercial_weekly

抓取频次：
   日更（02:00）：appstore_rank / androidrank / reddit / twitter (fapi.uk) /
                  comment_fetch / strategy_monitor / appmagic / fb_adlib(×5 国) /
                  sensor_tower + comment_label + commercial_strategy
   周更（周日 03:00）：iap_pricing / google_news / similarweb_traffic /
                       weekly_review / commercial_weekly + competitor_detail × 9
   按需：3 个 AI 任务用户在 dashboard 点按钮触发

抓取触发链：
   launchd / dashboard "同步" 按钮
      ↓
   scripts/daily_sync.py（3 阶段：重试 → 抓取 → AI）
      ↓
   失败入 retry_queue（5/30/120/360/720 min 退避）
   每小时 retry-only launchd 自动补救
      ↓
   完成后飞书发"📊 每日抓取完成"卡片（含 ✗ 失败明细）
```

---

## Key 配置情况

| Key | 用途 | 状态 |
|---|---|---|
| `CLAUDE_API_KEY` | flashapi 中转 | ✅ 已配 |
| `ANTHROPIC_API_KEY` | Claude 官方 fallback | ❌ 未配 |
| `UTOOLS_AUTH_TOKEN` | X (Twitter) 抓取（经 fapi.uk 第三方代理）| ⏳ 待配 — 小号 cookie，30 天失效，⚠️ 违反 X ToS |
| ~~`X_BEARER_TOKEN`~~ | ~~X 官方 API v2~~ | ⚪ **已弃用**（Free 层 100 reads/月不够，2026-04-30 迁 fapi.uk） |
| ~~`GOOGLE_API_KEY` + `GOOGLE_CSE_ID`~~ | ~~Google CSE~~ | ⚪ **不再需要**（迁到 RSS 模式，2026-04-30） |
| `MYSQL_DSN` | MySQL 主存储 | ✅ 已配（本地） |
| `REDIS_URL` | Redis 缓存 | ✅ 已配（本地） |
| `FEISHU_WEBHOOK_URL` + `FEISHU_KEYWORD` | 飞书通知 | ✅ 已配 |

Playwright 登录态：
-  `~/.appmagic-profile`
-  `~/.meta-adlib-profile`
-  `~/.sensortower-profile`
