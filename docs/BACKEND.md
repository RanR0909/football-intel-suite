# INTEL-OPS · 后端逻辑（v2.0 · 2026-04-30）

> 项目：Football_Intel_Suite — All Football 竞品情报系统
> 适用版本：v2.0（AI 重构后 / candidate ↔ competitor 严格分离 / Similarweb 简化版）
> 阅读对象：后端开发 / 接前端的同事 / 接手运维的人

---

## 0. 一句话架构

```
launchd 定时触发 sync 脚本 → 12 数据源并行抓取 → 落 MySQL/JSON/Redis →
4 个 AI 任务（haiku 4.5）做结构化处理 → alert_engine 出 7 类预警 →
聚合 dashboard_data.json → 前端读 + 飞书通知
```

**核心原则**：
- AI 只做结构化工作（分类 / 抽取 / 归一 / 翻译 / 短事实陈述），不写长文 / 不做主观判断 / 不给建议
- 所有抓取源失败 → 进 retry_queue（指数退避 [5min, 30min, 2h, 6h, 12h]）
- 所有 fact 表三路写入：MySQL 主存 + JSON 中间快照 + Redis 实时镜像（可选）

---

## 1. App 范围

**9 个竞品 + 1 个 baseline**（共 10 个 app，由 `data/competitors.json` 维护）：

| # | name | iOS | GP | website | 类型 |
|---|---|---|---|---|---|
| 1 | SofaScore | 1176147574 | com.sofascore.results | sofascore.com | 竞品 |
| 2 | FlashScore | 766443283 | eu.livesport.FlashScore_com | flashscore.com | 竞品 |
| 3 | OneFootball | 382002079 | de.motain.iliga | onefootball.com | 竞品 |
| 4 | 365Scores | 571801488 | com.scores365 | 365scores.com | 竞品 |
| 5 | Fotmob | 488575683 | com.mobilefootie.wc2010 | fotmob.com | 竞品 |
| 6 | LiveScore | 356928178 | com.livescore | livescore.com | 竞品 |
| 7 | AiScore | 1477171291 | com.onesports.score | aiscore.com | 竞品 |
| 8 | BeSoccer | 550928207 | com.resultadosfutbol.mobile | besoccer.com | 竞品 |
| 9 | 310Scores | 6449077229 | com.scores.tfz | 310scores.com | 竞品 |
| 10 | **AllFootball** | 1171012600 | com.allfootball.news | allfootballapp.com | **baseline**（自家产品 / 数据对照基准） |

**baseline 标识**：JSON 里 `is_baseline: true`，所有抓取流程同样处理；下游可用 `get_competitor_only()` vs `get_baseline_apps()` 分流展示。

**12 个区域**：us / gb / de / fr / es / it / br / mx / ng / sa / ae / jp（由 `data/regions.json` 维护）

---

## 2. 数据源（12 个 = 8 HTTP + 4 Playwright）

### 2.1 HTTP 抓取（8 个，aiohttp + retry）

| 源 | 抓什么 | 周期 | 实现 |
|---|---|---|---|
| `appstore_rank` | iOS 体育榜 top 100（多区）| 日 02:00 | `async_crawler/sources/appstore_rank.py` — iTunes RSS feeds |
| `androidrank` | 累计下载 + 评分历史 | 日 02:00 | `async_crawler/sources/androidrank.py` — androidrank.org HTML |
| `comment_fetch` | GP + iOS 用户评论（12 区）| 日 02:00 | `competitor_comment/comment_fetch.py` — 官方 review feeds |
| `reddit` | r/soccer 等帖子搜索 | 日 02:00 | `async_crawler/sources/reddit.py` — Reddit JSON API |
| `twitter` | 推文搜索 | 日 02:00 | `async_crawler/sources/twitter.py` — fapi.uk 第三方代理（apiKey） |
| `iap_pricing` | IAP 价格（cn 区，¥）| 周日 03:00 | `market_rank/scrape_qimai_iap.py` — qimai.cn Playwright（Apple 直抓被 IP redirect 卡死，已换数据源） |
| `google_news` | 商业新闻 RSS（business 关键词命中）| 周日 03:00 | `async_crawler/sources/google_news.py` — Google News RSS |
| `strategy_monitor` | 版本号 / 描述变化 | 日 02:00 | `strategy_monitor/changelog_*.py` — iTunes Lookup |

### 2.2 Playwright 持久 profile（5 个，需一次性人工登录）

| 源 | 抓什么 | profile 路径 | 备注 |
|---|---|---|---|
| `appmagic` | 全球 + 12 国排名 | `~/.appmagic-profile` | 免费账号即可 |
| `fb_adlib` | Meta 广告库（5 国 × 10 app = 50 query 拆任务并跑）| `~/.meta-adlib-profile` | per-country 拆并发 |
| `sensor_tower` | 月下载估算 / 收入 / 排名 | `~/.sensortower-profile` | 免费账号 |
| `qimai_iap` | App Store IAP 价格（cn 区）| `~/.qimai-profile/state.json` | 系统 Chrome + 关 `AutomationControlled` 反爬；登录方法详见 SETUP.md §5b |
| ~~`similarweb_traffic`~~ | （已死，CloudFront 拦 IP）→ 改用 `market_rank/scrape_sitedata.py`（SiteData 扩展 API） | — | 不需要 Playwright，纯 HTTP；UUID 在 `.env.local` |

### 2.3 共有约束

- `MAX_CONCURRENT = 4`（async_crawler.config）—— Phase 1 并发上限
- 每源遵守自己的 `rate_limit`（appstore_rank 0.5s / androidrank 2s / similarweb 2s）
- 失败重试：HTTP 类 3 次本地重试 → 仍失败进 `retry_queue`
- Cookie 失效（Playwright 类）：飞书红卡告警 + 跳过该源 + 该 source 进 `retry_queue`

---

## 3. AI 任务（v2 架构 · 4 个，全 Claude Haiku 4.5）

> 配置：`config/ai_tasks.json`（改这里就能换模型 / prompt，不用动业务代码）
> Prompt 模板：`ai_tasks/prompts/*.txt`（外置）
> 翻译表：`ai_tasks/translation_table.json`（180 条核心：50 球员 + 100 球队 + 30 联赛 + 50 体育术语）

| # | task | 输入 → 输出 | 触发 |
|---|---|---|---|
| 1 | `comment_label` | 评论 → `{language, translated_text, label}` (6 类) | 日更 02:30 批 300 条 |
| 2 | `entity_extract` | 评论 → `[{type, raw_value, canonical_id}]` (9 类实体) | 紧跟 1 |
| 3 | `alert_title` | metadata → `{title}` (≤50 字事实陈述) | alert_engine 命中后 |
| 4 | `app_classifier` | metadata → `{is_relevant, topic, categories, confidence}` | discover_peers 用 |

### 3.1 6 类标签（comment_label）

`complaint` 问题抱怨 / `feature_request` 高价值请求 / `competitor_compare` 竞品对比 /
`churn_signal` 流失信号 / `positive` 正向反馈 / `other` 其他

### 3.2 9 类实体（entity_extract）

`competitor` / `feature` / `league` / `player` / `device` /
`bug` / `localization` / `payment` / `language`

每个实体 → `canonical_id`（格式 `{type}_{slug}`，如 `player_ronaldo`），归一规则：
1. 先查 `entity_aliases` 表 alias → 命中即用
2. 没命中：AI 判断是否新别名 → 加 alias，`reviewed=false`
3. 完全新实体：AI 生成 canonical_id 入 `entity_aliases`，`reviewed=false`

### 3.3 8 选 1 topic（app_classifier）

`football` / `basketball` / `tennis` / `F1` / `cricket` / `multi_sport` / `non_sport`

### 3.4 8 多选 categories（app_classifier）

`news` / `score` / `prediction` / `tipster` / `betting` / `analytics` / `community` / `video`

### 3.5 统一调用入口

```python
from shared.ai_client import run_task
result = run_task("comment_label", context={"raw_text": "...", ...})
# → 返回 dict（output_format=json + json_strip_markdown=true）
```

**Endpoint 链**：flashapi（中转 / 默认）→ fallback 到 anthropic_official（HTTP 5xx 或 429 时）

**月成本**：~$50（38K comment_label + 38K entity_extract + 600 alert_title + 3K app_classifier）

---

## 4. 数据库结构（MySQL · 14 张表）

```
┌─ Lookup（人工 seed，alembic init/migration 灌入）
│   competitors            ── 10 行（9 + AF baseline）
│   regions                ── 12 行
│
├─ Fact - 抓取（async_crawler / market_rank 写）
│   reviews                ← comment_fetch + comment_label AI 写回 label/lang/translated_text
│   ad_creatives           ← fb_adlib（含 region / spend / impression）
│   iap_items              ← iap_pricing（每抓不去重，看价格趋势）
│   market_rank_snapshots  ← appstore_rank / appmagic / sensor_tower / androidrank
│   community_posts        ← reddit / twitter（uniq by source+post_id）
│   website_traffic        ← similarweb（月级 UPSERT，UNIQUE(competitor_id, snapshot_month)）
│
├─ Fact - AI v2（自动写）
│   entity_aliases         ── canonical 实体表（reviewed=false 等周批人审）
│   comment_entities       ── 评论 ↔ 实体 多对多（uniq review_id+canonical_id）
│   alerts                 ── 7 类预警事件 + AI 写 title
│   app_classifications    ── unknown app AI 分类（candidate 候选池）
│   failed_ai_jobs         ── AI 失败队列（重试耗尽后写入）
│
└─ Ops
    sync_log               ── 抓取作业日志（rolling 50）
```

### 4.1 关键表 schema 速记

#### `reviews` (含 AI v2 字段)
```
id, competitor_id, region_code, platform ENUM('gp','ios'),
score (1-5), version, content,
label, language, translated_text, labeled_at,    -- AI v2 写入
at, fetched_at
```

#### `market_rank_snapshots`
```
id, source ENUM('appmagic','appstore_rank','sensor_tower','androidrank'),
region_code, competitor_id (NULL = 非 tracked),
name, rank_value, delta, downloads, downloads_num, revenue_num,
snapshot_date, fetched_at
```

#### `website_traffic` (Similarweb 简化版 · 20 列)
```
id, competitor_id, domain, snapshot_month,
monthly_visits / monthly_visits_num,
avg_visit_duration / avg_visit_duration_sec,
pages_per_visit, bounce_rate,
global_rank, country_rank, country_rank_country, category_rank,
male_share, female_share,
top_countries_json, similar_sites_json, raw_text,
fetched_at
```
**注意**：device split / 6 channel breakdown / top_keywords 已永久删除（trial-only 不稳定字段）

#### `entity_aliases`
```
canonical_id (PK, 格式 {type}_{slug}),
entity_type, primary_name, english_name,
aliases (JSON list), created_at, reviewed BOOL, reviewed_at
```

#### `alerts`
```
id, alert_type ENUM(7 种), severity ENUM('high','mid','low'),
competitor_id, app_name, metadata_json,
title VARCHAR(120), rule_triggered VARCHAR(64),
fired_at, status ENUM('new','ack','dismissed')
```

#### `app_classifications`
```
id, app_id, platform ENUM('gp','ios'),
bundle_id, name, publisher, category,
description_excerpt, matched_keywords (JSON),
is_relevant, topic, categories (JSON), confidence, rejection_reason,
classified_at,
UNIQUE(app_id, platform)
```

#### `failed_ai_jobs`
```
id, task_name, payload_json, error_msg, error_kind,
attempts, first_failed_at, last_attempt_at, resolved_at
```

### 4.2 辅助存储

**Redis**（可选 — 未配置时退化为 JSON-only）：
- `sync_state` (HASH) — 各源 last_success / last_attempt 时间戳，`is_fresh()` 判定
- `retry_queue` (ZSET) — 失败任务 + due_at（指数退避）
- `sync_log:recent` (LIST) — 最近 100 条 sync_log 镜像，dashboard 实时面板用

**JSON 中间快照**（`data/*.json`）：
- 每个抓取源的标准 shape（`{timestamp, source, competitor, data}`）
- aggregator 直接消费 → 生成 `dashboard_data.json` 给前端
- `data/raw/*` — 调试用快照（comment 原文 / Similarweb markdown 等）

---

## 5. 调度链路

### 5.1 每日 02:00（launchd → `scripts/daily_sync.py`）

```
Phase 0 · 重试队列
   └─ 拉 retry_queue 中 due_at <= now 的任务，逐个 _run_one
      指数退避：[5min, 30min, 2h, 6h, 12h]，max_attempts=5

Phase 1 · 抓取（并行 MAX_CONCURRENT=4，逻辑上 8 + 4 = 12 源；
              fb_adlib 实际拆成 5 个 per-country 子任务，故 sync_log 里通常显示 13 条）
   ├─ HTTP (6): appstore_rank / androidrank / comment_fetch / reddit /
   │           twitter / strategy_monitor   （周更才跑 iap_pricing / google_news / similarweb_traffic）
   └─ Playwright: appmagic / sensor_tower + fb_adlib_{us,gb,br,mx,ng}

Phase 2 · AI 串行
   ├─ 2.1 discover_peers       ── 扫 appstore_rank top 100 unknown app（30 天缓存）
   │      → 入 app_classifications（candidate 池，永不写 competitors）
   └─ 2.2 ai_pipeline           ── 串：
            ① 取 reviews.labeled_at IS NULL 的（默认 limit 300）
            ② 逐条 comment_label → UPDATE reviews.{label,language,translated_text,labeled_at}
            ③ 逐条 entity_extract → INSERT entity_aliases + comment_entities
            ④ alert_engine 跑 7 类规则
                → 命中事件 → alert_title 生成 ≤50 字 title
                → INSERT alerts 表

Phase 3 · 聚合
   └─ aggregate                ── 把所有源汇成 dashboard_data.json

完成后 → 飞书 "📊 每日抓取完成" 卡片（绿/橙/红 按失败数）
```

### 5.2 每周日 03:00（launchd → `scripts/weekly_sync.py`）

```
Phase 0 · retry_queue（含 daily 留下的）

Phase 1 · 4 个周更任务（串行）
   1. iap_pricing             ── 价格 7 天才变一次
   2. google_news             ── RSS 商业新闻（业务关键词命中）
   3. similarweb_traffic       ── 网站流量
   4. aggregate                ── 重生成 dashboard_data.json

完成后 → 飞书 "📅 周更完成" 卡片
```

### 5.3 每小时（retry-only launchd）

只跑 `retry_queue` 中到期的项，不抓新数据。处理过任务才发飞书重试汇总。

---

## 6. alert_engine 7 类规则

`ai_tasks/alert_engine.py` — 跑在 ai_pipeline 末尾。

| 类 | 触发条件 | 数据源 | 严重度 | 去重 |
|---|---|---|---|---|
| `ranking` | 24h 内 rank 变 ≥ 5 名 | `market_rank_snapshots` | 变 ≥10 = high, 否则 mid | 同 (type, app, day) 1 次 |
| `commercial` | IAP 价 ±10% 影响 ≥ 5 区 | `iap_items` | 变 ≥30% = high | 同 (type, app, day) 1 次 |
| `news` | Google News business 关键词命中 | `data/async_google_news.json` | mid | 每 headline 独立（不去重）|
| `release` | 7 天内首次出现的新 version + obs ≥ 5 | `reviews.version` | low | 每 version 独立 |
| `rating` | 4 天评分均值跌 ≥ 0.3 | `reviews.score` | 跌 ≥0.5 = high | 同 (type, app, day) 1 次 |
| `churn` | 7 天 churn_signal 占比涨 ≥ 50% | `reviews.label` | 涨 ≥100% = high | 同 (type, app, day) 1 次 |
| `ads` | 7 天广告投放变 ±50% | `ad_creatives` | 变 ≥3× / ≤0.2× = high | 同 (type, app, day) 1 次 |

**实测今天**：1 ranking + 7 news + 9 release = 17 alerts。

每条 alert：

```python
{
  "id": 123,
  "alert_type": "ranking",
  "severity": "high",
  "app_name": "Sofascore",
  "competitor_id": 1,
  "metadata": {"region": "us", "old_rank": 14, "new_rank": 6, "change": 8, ...},
  "title": "Sofascore 美国体育榜 #14 → #6 · ↑ 8 名",   # AI 写
  "rule_triggered": "rank_delta_5plus_24h",
  "fired_at": "...",
  "status": "new"
}
```

---

## 7. candidate ↔ competitor 严格分离

> ⚠️ **铁律**：`app_classifications` 和 `competitors` 完全独立。AI 永不自动跨界写入。

```
appstore_rank top 100
    ↓ (Phase 2.1 daily)
discover_peers
    ↓ 过滤 已在 competitors.json 的 app
    ↓ iTunes Lookup 取 description / publisher
    ↓ classify_app（30 天缓存命中 = 不调 AI）
    ↓ INSERT app_classifications 表
candidate 列表（is_relevant=true + topic ∈ {football, multi_sport} + conf ≥ 0.85）
    ↓
人工 curate（你看 list 后手动改 competitors.json）
    ↓
competitors lookup（人工守门）
```

**人工 curation 流程**：
1. `python3 -m ai_tasks.discover_peers list` → 看候选清单
2. 觉得某个值得跟踪 → 手工编辑 `data/competitors.json` 加一条
3. 直接 `INSERT INTO competitors (name, gp_package, ios_app_id, bundle_id) VALUES (...)`
4. 第二天 daily_sync 自动开始抓那个 app 的所有 12 个数据源

---

## 8. 异常 & 退化策略

| 失败类型 | 处理 |
|---|---|
| HTTP 抓取源 5xx / 网络超时 | 本地重试 3 次 → 进 retry_queue → 下小时重试 |
| 连续 5 次失败 | 飞书红卡 + 暂停该源 24h |
| Playwright cookie 失效 | 即时飞书红卡 + 跳过该源 |
| AI 调用 HTTP 错 / 超时 | 重试 1 次 → 失败进 `failed_ai_jobs`（kind=http） |
| AI 输出 JSON 解析失败 | 重试 1 次 → 失败进 `failed_ai_jobs`（kind=json_parse） |
| AI label 不在 6 类 | 兜底归 `other` |
| AI entity type 不在 9 类 | 直接丢弃该实体 |
| AI alert title > 50 字 | 截断到 50 字（不重新调用） |
| AI app_classifier topic 不合规 | 强制归 `non_sport` + `is_relevant=false` |
| MySQL 未配置（MYSQL_DSN 空）| 所有 dao 静默 return 0 / None，JSON 主路径不动 |
| Redis 未配置（REDIS_URL 空）| sync_state 退化为内存判定，retry_queue 失效（但 Phase 1 仍能跑）|
| Twitter token 失效 | fapi 返回 401 → 跳 + 飞书 |
| Similarweb Cloudflare 拦截 | 触发 CloudflareBlocked → 停抓 + 飞书提示重跑 login |

---

## 9. 飞书通知（webhook）

`shared/feishu_notify.py` — 走 `FEISHU_WEBHOOK_URL` 环境变量（未配置时静默跳过）。

| 触发场景 | 卡片 | 颜色规则 |
|---|---|---|
| daily_sync 完成 | "📊 每日抓取完成" | green=0 fail / orange ≤2 fail / red ≥3 fail |
| weekly_sync 完成 | "📅 周更完成" | 同上 |
| Cookie 失效（fb_adlib / sensor_tower / appmagic / similarweb）| 即时红色卡片 | red |
| 每小时 retry-only 实际处理过任务 | "🔁 重试汇总" | 默认 |
| AI 失败队列累计 ≥ 10 | "⚠️ AI 失败告警" | red（dashboard 实现，未自动）|

---

## 10. 关键入口文件

```
scripts/
├── daily_sync.py             — 主调度（launchd 入口，每日 02:00）
└── weekly_sync.py            — 周更调度（launchd 入口，周日 03:00）

ai_tasks/                     — AI v2 任务包
├── comment_label.py          — 任务 1 实现
├── entity_extract.py         — 任务 2 实现
├── alert_title.py            — 任务 3 实现
├── app_classifier.py         — 任务 4 实现
├── alert_engine.py           — 7 类预警规则检测器
├── discover_peers.py         — 候选发现（含 list 子命令）
├── run_pipeline.py           — AI 管道批量驱动器
├── prompts/                  — 4 个 .txt 外置 prompt
└── translation_table.json    — 球员 / 球队 / 联赛 / 术语 翻译表

shared/                       — 共享层
├── ai_client.py              — 统一 AI 调用入口（运行时 / fallback）
├── env_loader.py             — .env.local 加载
├── db.py                     — SQLAlchemy session 工厂
├── models.py                 — 14 张 ORM 模型
├── feishu_notify.py          — 飞书 webhook 客户端
├── sync_state.py             — Redis sync_state 客户端
├── retry_queue.py            — Redis retry_queue 客户端
└── dao/                      — 11 个 DAO 模块（MySQL CRUD）
    ├── reviews.py
    ├── ads.py
    ├── iap.py
    ├── rank.py
    ├── community.py
    ├── entity_aliases.py
    ├── comment_entities.py
    ├── alerts.py
    ├── app_classifications.py
    ├── failed_ai_jobs.py
    └── sync_log.py

async_crawler/                — HTTP 抓取（异步）
├── base.py                   — BaseCrawler（aiohttp + Semaphore + retry）
├── config.py                 — MAX_CONCURRENT / REQUEST_TIMEOUT
├── db.py                     — 写 JSON + 调 dao
└── sources/                  — 8 个 HTTP 源

market_rank/                  — Playwright 抓取
├── scrape_appmagic.py
├── scrape_fb_adlib.py
├── scrape_sensor_tower.py
└── scrape_similarweb.py

competitor_comment/
└── comment_fetch.py          — 评论抓取（不带 AI）

main_dashboard/
├── dashboard_server.py       — HTTP server（dashboard 前端 + on-demand API）
└── (已删，v1 HTML 渲染入口；v2 用 data_pipeline/aggregator.py)

config/
├── ai_tasks.json             — 4 个 AI 任务配置
├── google_news.json          — Google News 关键词 + 黑名单
└── ...

data/
├── competitors.json          — 10 个 app 元信息（人工 curate）
├── regions.json              — 12 个区域配置
├── dashboard_data.json       — 聚合后的看板数据（前端读这个）
└── raw/                      — 调试用快照
```

---

## 11. 数据流示例（一条评论的旅程）

```
①  comment_fetch.py 抓 GP review
    raw_text="Esta app es lenta cuando intento ver el Real Madrid live"
    score=2, region=es, version=v3.18.5
    ↓
②  shared/dao/reviews.upsert_reviews
    INSERT reviews 行 (label=NULL, labeled_at=NULL)
    ↓
③  02:30 ai_pipeline 拉 labeled_at IS NULL 的批
    ↓
④  comment_label AI 调用
    {language: "es", translated_text: "这个 app 在我想看皇马 live 时很慢",
     label: "complaint"}
    ↓
⑤  UPDATE reviews 写回 4 字段
    ↓
⑥  entity_extract AI 调用
    [{type: "bug", raw_value: "lenta", canonical_id: "bug_lag", ...},
     {type: "team", raw_value: "Real Madrid", → 翻译表命中 → 但 team 不在 9 类 → 丢弃}]
    ↓
⑦  INSERT entity_aliases (bug_lag, reviewed=false)
    INSERT comment_entities (review_id=999, canonical_id="bug_lag")
    ↓
⑧  alert_engine churn 规则扫描：
    "ES 区 Sofascore 7 天 churn_signal 占比 8% → 14%（涨 75%）"
    ↓
⑨  alert_title AI 生成: "Sofascore 西区 churn 信号 8% → 14% · 7 天"
    ↓
⑩  INSERT alerts 行 (severity=mid)
    ↓
⑪  03:00 aggregate 把所有源汇到 dashboard_data.json
    ↓
⑫  前端 fetch /api/data/dashboard_data
    ↓
⑬  飞书 webhook 推完成卡片
```

---

## 12. CLI 速查

### 抓取
```bash
# 全量同步（与 launchd 同入口）
python3 scripts/daily_sync.py
python3 scripts/weekly_sync.py

# 单源
python3 -m async_crawler --sources appstore_rank
python3 -m async_crawler --sources reddit,twitter

# Playwright 登录（一次性）
python3 -m market_rank.scrape_appmagic login
python3 -m market_rank.scrape_fb_adlib login
python3 -m market_rank.scrape_sensor_tower login
python3 -m market_rank.scrape_similarweb login
```

### AI
```bash
# AI 主管道
python3 -m ai_tasks.run_pipeline                     # 默认（评论 + 预警）
python3 -m ai_tasks.run_pipeline --skip-comments     # 只跑 alert_engine
python3 -m ai_tasks.run_pipeline --skip-alerts       # 只跑评论管道
python3 -m ai_tasks.run_pipeline --dry-run

# 候选发现
python3 -m ai_tasks.discover_peers                   # scan + 列候选
python3 -m ai_tasks.discover_peers list              # 不抓只列已有候选
python3 -m ai_tasks.discover_peers --limit 20
python3 -m ai_tasks.discover_peers --topic football

# 单个 alert engine
python3 -m ai_tasks.alert_engine --type ranking
python3 -m ai_tasks.alert_engine --dry-run
```

### 数据库
```bash
# 应用迁移
alembic upgrade head

# 看当前迁移状态
alembic current

# 创建新迁移
alembic revision -m "..."
```

### 看板
```bash
# 起 dashboard server（默认 :8899）
python3 main_dashboard/dashboard_server.py

# 重生成 dashboard_data.json
python3 -m data_pipeline.aggregator
```

---

## 13. 配置文件

### `config/ai_tasks.json`
4 个任务的统一配置。改这里就能：
- 换模型（默认全 haiku_4_5）
- 调 max_tokens / temperature
- 切 endpoint（flashapi ↔ anthropic_official）
- 改 prompt 文件路径

### `config/google_news.json`
- 9 竞品的 broad / business 查询关键词
- 17 source blocklist（社媒 / 招聘站 / 自家网站）
- business 关键词 clause（funding / acquires / launches / ...）

### `data/competitors.json`
10 个 app 的元信息。**这是人工 curate 的真实数据源**，不要让 AI 自动写入。

### `data/regions.json`
12 个区域配置（code / lang / label）。

---

## 14. 环境变量（`.env.local`）

```bash
# AI（必须至少配一个）
CLAUDE_API_KEY=...                    # flashapi 中转（默认）
ANTHROPIC_API_KEY=...                 # 官方 fallback（可选）

# Twitter
UTOOLS_AUTH_TOKEN=...                 # fapi.uk apiKey（待付费）

# MySQL（必须 — 不配则 dao 全静默 noop）
MYSQL_DSN=mysql+pymysql://intelops:dev@localhost:3306/football_intel?charset=utf8mb4

# Redis（可选 — 不配则 sync_state / retry_queue 退化）
REDIS_URL=redis://localhost:6379/0

# 飞书（可选）
FEISHU_WEBHOOK_URL=...
FEISHU_KEYWORD=INTEL-OPS

# AI 任务级临时覆盖（dev 调参用）
# AI_OVERRIDE__comment_label__temperature=0.0
# AI_OVERRIDE__alert_title__max_tokens=128
```

`.env.local` 在 `.gitignore` 里 — 永不入仓。

---

## 15. 启动流程（新机器上手）

```bash
# 1. 克隆 + 装依赖
git clone https://github.com/RanR0909/football-intel-suite.git
cd football-intel-suite
pip install -r requirements.txt
playwright install chromium

# 2. 起 MySQL + Redis（用 docker-compose）
docker compose up -d

# 3. 建 schema
alembic upgrade head

# 4. 配 .env.local
cp .env.local.example .env.local
# 填入 CLAUDE_API_KEY / MYSQL_DSN / 等

# 5. 一次性 Playwright 登录
python3 -m market_rank.scrape_appmagic login
python3 -m market_rank.scrape_fb_adlib login
python3 -m market_rank.scrape_sensor_tower login
python3 -m market_rank.scrape_similarweb login

# 6. 跑一次全量同步看是否通
python3 scripts/daily_sync.py --dry-run    # 看任务图
python3 scripts/daily_sync.py               # 真跑

# 7. 挂 launchd（参考 scripts/launchd/*.plist 模板）
launchctl load ~/Library/LaunchAgents/com.intelops.daily-sync.plist
```

---

## 16. 监控 / 排错

### 看健康度
```sql
-- 各源最近抓取
SELECT script, MAX(started_at) as last_run, success
FROM sync_log
GROUP BY script ORDER BY last_run DESC;

-- AI 失败队列
SELECT task_name, COUNT(*) as n, MAX(last_attempt_at) as last
FROM failed_ai_jobs
WHERE resolved_at IS NULL
GROUP BY task_name;

-- 今天的 alerts
SELECT alert_type, severity, app_name, title
FROM alerts WHERE DATE(fired_at) = CURDATE()
ORDER BY severity DESC, fired_at DESC;
```

### Dashboard 健康卡片
`/api/status` 返回：
- 各 fact 表行数
- 各源最近抓取时间
- retry_queue 当前长度
- failed_ai_jobs 未解决数
- 各 lookup 表（competitors / regions）行数

---

## 17. 后续待办

| 项 | 状态 |
|---|---|
| Twitter fapi 付费 token | 等老板 — 拿到后覆盖 `.env.local` 那行即可，代码不动 |
| 候选 → competitor 前端展示重构 | 等用户具体指令 |
| 旧 AI v1 文件 | 已 git rm 17 个 |
| Similarweb trial-only 字段 | 已永久删除（migration 0008） |

---

## 附录 A · 已被 v2 删除 / 弃用的功能

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
| `comment_translate` (独立任务) | 已合入 `comment_label` |

按 `AI_tasks_spec_v1_1.md` 严格禁令：AI 不写长文 / 不做主观判断 / 不做情感分析 / 不给建议。

---

## 附录 B · 迁移历史

| Migration | 日期 | 说明 |
|---|---|---|
| 0001_init | - | 8 张初始表 + lookup seed |
| afec0ab9235a | - | market_rank_snapshots 加 downloads_num / revenue_num |
| 543643e209f9 | - | rank_source enum 加 androidrank |
| 0006_website_traffic | 2026-04-30 | similarweb 初版 22 列 |
| 0007_website_traffic_extra | 2026-04-30 | 加 ranks / demographics / similar_sites |
| 0008_drop_trial_only | 2026-04-30 | 删 9 个 trial-only 列（device / 6 channels / keywords） |
| 0009_seed_allfootball | 2026-04-30 | seed AllFootball 入 competitors lookup |
| 0010_ai_v2_schema | 2026-04-30 | reviews 加 AI 字段 + 4 张新表（entity_aliases / comment_entities / alerts / failed_ai_jobs）|
| 0011_app_classifications | 2026-04-30 | 加 app_classifications 表（task #4 candidate 池）|

---

文档版本 v2.0 · 2026-04-30
对应 commit：`8750557`（rm AI v1 文件 17 个之后的状态）
