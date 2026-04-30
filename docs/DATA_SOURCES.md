# 数据源

> 9 个 竞品 + 1 个 baseline（AllFootball，自家产品 / 数据分析对照基准） × 12 个区域，13 个数据源 + 4 个 AI 任务。
>
> **关于 baseline**：`AllFootball` 在 `data/competitors.json` 标 `is_baseline: true`。所有 14 个数据源会
> 自动一并抓取它（与 9 竞品同流程同 schema）；下游 dashboard / 报表后续可用 `get_competitor_only()`
> vs `get_baseline_apps()` helper 区分展示。

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

✅ **只抓"永久免费可用"字段** —— device split / 6 渠道分布 / top_keywords 仅 8 天 Premium Trial 期间可见，trial 过期后 gated。为避免长期 null 列，已从 schema 中移除（migration 0008 drop）。

| 字段 | 含义 | 例 |
|---|---|---|
| `monthly_visits` / `_num` | 月访问量（原文 + 解析数值）| `"85M"` / `85000000` |
| `avg_visit_duration` / `_sec` | 平均停留时长 | `"00:06:23"` / `383` |
| `pages_per_visit` | 平均访问页数 | `4.32` |
| `bounce_rate` | 跳出率（小数 0–1）| `0.5254` |
| `global_rank` | 全球排名 | `635` |
| `country_rank` / `_country` | 主要国家排名 + 国名 | `298` / `"Brazil"` |
| `category_rank` | 行业 / 分类排名 | `9` |
| `top_countries` (JSON, top 5) | Top 5 国家 + 占比 | `[{country, share}, ...]` |
| `male_share` / `female_share` | 性别画像（anonymous 才显示） | `0.76` / `0.24` |
| `similar_sites` (JSON, top 10) | 相似网站 + 亲和度（anonymous 才显示） | `[{domain, affinity}, ...]` |
| `raw_text` | main innerText 前 8000 字（调试） | 整段页面文案 |

`male/female_share` + `similar_sites` 在 trial 期内可能 null（trial 着重 Marketing Channels），trial 结束 / 登出后激活。
所有字段都接受 NULL，dashboard 缺失自动渲染 `—`。

入库 `website_traffic` 表，`UNIQUE (competitor_id, snapshot_month)`，月内重复抓 UPSERT 同一行。

CLI：
```bash
python3 -m market_rank.scrape_similarweb              # 正常抓（用 ~/.similarweb-profile）
python3 -m market_rank.scrape_similarweb --domain X   # 只抓一个站
python3 -m market_rank.scrape_similarweb --headed     # 显示浏览器调试
python3 -m market_rank.scrape_similarweb --anonymous --domain X   # 不带 cookie，验证字段集（不入 MySQL）
python3 -m market_rank.scrape_similarweb login        # 一次性手动过 CF + profile 持久化
```

---

## AI 分析（v2 架构 · 4 个任务，仅做结构化工作）

> **2026-04-30 重构**：按 `AI_tasks_spec_v1_1.md` + `app_classifier_prompt.txt` 全部重做。
> 总原则：**AI 只做结构化工作**（分类 / 抽取 / 归一 / 翻译 / 短事实陈述），不做主观判断 / 不写长文 / 不提建议 / 不做情感分析。
> 全部走 Claude Haiku 4.5。月成本估 ~$50。

### 13. `comment_label` — 单条评论翻译 + 6 类标签（实时 / daily 触发）

**输入**：`{comment_id, raw_text, language_hint?}`
**输出**：`{language, translated_text, label}`

6 类标签：`complaint` / `feature_request` / `competitor_compare` / `churn_signal` / `positive` / `other`

翻译策略：人名 / 球队名 / 联赛名 / 体育术语用 `ai_tasks/translation_table.json`（180 条核心条目）映射；竞品名 / app 名 / 产品名保留原文。

存储：写回 `reviews` 表的 `label` / `language` / `translated_text` / `labeled_at`。

---

### 14. `entity_extract` — 9 类实体抽取 + canonical_id 归一（紧跟 13 后）

**输入**：`{comment_id, translated_text, raw_text, label}`
**输出**：`{entities: [{type, raw_value, canonical_id, is_new_alias, is_new_canonical}]}`

9 类实体：`competitor` / `feature` / `league` / `player` / `device` / `bug` / `localization` / `payment` / `language`

归一逻辑：先查 `entity_aliases` 表，命中即用；未命中则 AI 判断是新别名还是新 canonical（命名 `{type}_{slug}`，`reviewed=false` 等人工审核）。

存储：
- `entity_aliases` 表（新 canonical / 新别名）
- `comment_entities` 表（评论 ↔ 实体多对多）

---

### 15. `alert_title` — 7 类预警事件文案生成（每日 02:30 alert_engine 调用）

**架构**：规则层（Python，扫 fact 表）+ AI 文案层（生成 ≤50 字事实陈述）。AI 只负责后者。

**7 类预警**：

| alert_type | 触发条件 | metadata 字段 |
|---|---|---|
| `ranking` | 24h 内 rank 变动 ≥ 5 名 | region, source, old_rank, new_rank, change |
| `commercial` | IAP 价格变动 ≥ ±10% 影响 ≥ 5 区 | iap_name, old_price_usd, new_price_usd, change_pct, regions_count |
| `news` | Google News business 关键词命中 | headline, source, keyword_matched, link |
| `release` | 7 天内首次出现的新 version | version, first_seen, obs_count |
| `rating` | 4 天评分均值下跌 ≥ 0.3 星 | region, old_rating, new_rating, days |
| `churn` | 7 天 churn_signal 占比上升 ≥ 50% | old_pct, new_pct, period_days |
| `ads` | 7 天广告投放量变化 ≥ ±50% | count_old, count_new, period_days |

**输出 title 风格**（≤50 字事实陈述）：
- ✅ "Sofascore 美国体育榜 #14 → #6 · 24h 内 ↑ 8 名"
- ✅ "365Scores VIP 月订阅 $4.99 → $6.99 · +40% · 9 区同步"
- ❌ "Sofascore 强势上涨，威胁 AF 在美区的地位"（含解读）
- ❌ "365Scores 涨价过猛，可能引发用户流失"（含推测）

存储：`alerts` 表

---

### 16. `app_classifier` — App Store / GP metadata → 结构化分类（按需触发）

**输入**：`{app_id, platform, name, publisher, description, category, matched_keywords}`
**输出**：`{is_relevant, topic, categories, confidence, rejection_reason}`

**Topic（8 选 1）**：`football` / `basketball` / `tennis` / `F1` / `cricket` / `multi_sport` / `non_sport`
**Categories（8 多选）**：`news` / `score` / `prediction` / `tipster` / `betting` / `analytics` / `community` / `video`

**用途**：
- appstore_rank 抓 top 100 后扫描所有 `competitor_id IS NULL` 的未跟踪 app，自动判断是否是 peer
- 关键词搜索（"football"/"soccer"/"live scores"）发现的新 app 入库前先分类
- 人工提交 bundle_id / iOS app id 让 AI 帮忙判断

**Decision rules（从 prompt 来）**：
- 足球管理游戏（Football Manager / FIFA Mobile）→ `non_sport`, `is_relevant=false`
- 球类休闲游戏（Soccer Stars 等）→ `non_sport`, `is_relevant=false`
- 私人记分工具（Tennis Score Pad）→ `non_sport`, `is_relevant=false`
- 体育直播 app（ESPN+ / DAZN）→ `is_relevant=true`，含 `video`
- 博彩 app（Bet365）→ `is_relevant=true`，含 `betting`
- 体育新闻聚合（All Football）→ `is_relevant=true`，含 `news`

**缓存**：`(app_id, platform)` 30 天内已分类的不重新调 AI（`is_already_classified` 短路）

**实测样例**（4/4 与 spec 例子完美对齐）：
| 输入 | 输出 |
|---|---|
| All Football - Soccer scores | `is_relevant=true, topic=football, categories=[score,news,analytics,video]` |
| Football Manager 2026 Mobile | `is_relevant=false, topic=non_sport, reason="足球管理类游戏"` |
| Bet365 Sports Betting | `is_relevant=true, topic=multi_sport, categories=[betting,score]` |
| Tennis Score Pad | `is_relevant=false, topic=non_sport, reason="私人记分工具,非内容向 app"` |

**存储**：`app_classifications` 表（`UNIQUE(app_id, platform)`），重复分类 UPSERT 同一行

**自动发现 peer 候选**（`ai_tasks.discover_peers` 管道，已挂 daily_sync Phase 2）：

⚠️ **严格分离** — `app_classifications`（候选池） 和 `competitors`（跟踪池）**完全独立**：
- candidate **永远不会** 自动写入 `competitors` 表 / `competitors.json`
- 候选只用于人工浏览决定要不要手工 curate
- 没有 `--auto-promote` 选项

```
appstore_rank top 100 →
  过滤 competitor_id IS NULL（不在 competitors.json）→
  iTunes Lookup 取 description / publisher →
  classify_app（30 天缓存命中 = 不调 AI）→
  candidate filter: is_relevant=true + topic ∈ {football, multi_sport} + conf ≥ 0.85 →
  全部入 app_classifications 表
  candidate 列表只在脚本输出 + 通过 list 子命令查询
```

**实测**（2026-04-30 跑 US sports top 100）：
- 97 个未知 app；20 个抽样 → 9 个 peer candidate（全 multi_sport）：

| Candidate | Topic | Categories | Conf |
|---|---|---|---|
| ESPN: Live Sports & Scores | multi_sport | score / news / video / analytics | 0.98 |
| FanDuel Sportsbook & Casino | multi_sport | betting | 0.97 |
| DraftKings Sportsbook & Casino | multi_sport | betting | 0.97 |
| bet365 - Sportsbook & Casino | multi_sport | betting / video / score | 0.97 |
| Fanatics Sportsbook & Casino | multi_sport | betting | 0.95 |
| Betr Picks & Sportsbook | multi_sport | betting / prediction | 0.93 |
| PrizePicks - Sports Picks | multi_sport | betting / prediction | 0.93 |
| FanDuel Predicts | multi_sport | prediction / betting | 0.90 |
| MLB | multi_sport | video / news / score | 0.90 |

CLI：
```bash
# 抓 + 分类 + 列候选（默认）
python3 -m ai_tasks.discover_peers                       # scan 模式（默认）
python3 -m ai_tasks.discover_peers --limit 20            # 限制处理 20 个
python3 -m ai_tasks.discover_peers --topic football      # 只看 football 候选
python3 -m ai_tasks.discover_peers --min-confidence 0.9  # 提高门槛

# 不抓只列（查 app_classifications 表里现有候选）
python3 -m ai_tasks.discover_peers list
python3 -m ai_tasks.discover_peers list --include-already-tracked   # 含已跟踪的（debug）
```

**人工 curation 流程**：你看到 candidate 觉得值得跟踪，就**手动**编辑 `data/competitors.json` 加上对应条目，重跑 `alembic upgrade head` （0009 的 seed 模式只对新 name 生效）或直接 INSERT 到 MySQL `competitors` 表 — 该 app 下次 daily_sync 会被所有数据源照常抓。

---

### 已删除（v2 不允许的功能）

按 spec 严格禁令"AI 不写长文 / 不做主观判断 / 不做情感分析"：

| 已删除 | 原因 |
|---|---|
| `weekly_review` (3000 字周报) | 长文报告 |
| `competitor_detail × 9` (2000 字 / 竞品) | 长文报告 |
| `commercial_weekly` (商业建议) | 给建议 |
| `commercial_monetize_tag` / `commercial_intent` | 主观判断 |
| `ads_strategy` (受众画像 / 卖点 / 风险解读) | 主观策略 |
| `community_insights` (话题分布 / 机会解读) | 跨评论趋势总结 |
| `review_3d` (3 天痛点摘要) | 长文摘要 |
| `strategy_monitor_analysis` | 主观判断 |
| `comment_translate` (独立翻译) | 已合入 `comment_label` |

---

### 错误处理 / 约束

| 错误 | 处置 |
|---|---|
| 模型超时 | 重试 1 次，仍失败 → `failed_ai_jobs` 死信 |
| JSON 解析失败 | 重试 1 次，仍失败 → `failed_ai_jobs` |
| label 不在 6 类 | 默认归 `other` |
| entity type 不在 9 类 | 丢弃该实体 |
| alert title > 50 字 | 截断（不重新调用） |

成本估算（haiku 4.5）：

| 任务 | 月调用 | 月成本 |
|---|---|---|
| comment_label | ~38,000 | ~$30 |
| entity_extract | ~38,000 | ~$15 |
| alert_title | ~600 | ~$2 |
| app_classifier | ~3,000（top 100 × 30 天 ÷ 30 天缓存命中率 70%） | ~$3 |
| **合计** | | **~$50** |

---

## 数据流

```
13 个源 + 3 个 AI 任务 → 抓 / 算
   ├─ HTTP 抓取（9）：appstore_rank / androidrank / comment_fetch / reddit /
   │                  twitter (fapi.uk) / iap_pricing / google_news / strategy_monitor
   ├─ Playwright（4）：appmagic / fb_adlib / sensor_tower / similarweb_traffic
   └─ AI v2（4）：comment_label / entity_extract / alert_title / app_classifier  (haiku 4.5 only)

抓取频次：
   日更（02:00）：appstore_rank / androidrank / reddit / twitter (fapi.uk) /
                  comment_fetch / strategy_monitor / appmagic / fb_adlib(×5 国) / sensor_tower
   日更 AI 管道（02:30）：
     1. ai_tasks.discover_peers     — 用 app_classifier 扫 appstore_rank 未知 app（30 天缓存）
     2. ai_tasks.run_pipeline       — comment_label + entity_extract + alert_engine
   周更（周日 03:00）：iap_pricing / google_news / similarweb_traffic + 看板重生成
   按需：（dashboard 已下线 review_3d / ads_strategy / community_insights 三个按钮）

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
