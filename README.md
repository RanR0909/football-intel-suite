# INTEL-OPS

面向足球 / 体育 App 的竞品情报平台。统一监控 **App Store / Google Play / Reddit / X / Meta 广告库** 上的排名、评论、版本更新、商业化动作和社媒舆情，统一聚合到 HTML 看板，含 AI 触发的深度分析。

---

## 模块拓扑

```
┌── 数据采集（7 大数据源） ──────────────────────────────────────────┐
│                                                                      │
│  strategy_monitor/         ─→ data/strategy_monitor.json   产品动态  │
│  market_rank/              ─→ data/market_rank.json        排名+收入 │
│  competitor_comment/       ─→ data/competitor_comments.json 用户评论 │
│  commercial_strategy/      ─→ data/commercial_strategy.json 商业 IAP │
│  async_crawler/sources/    ─→ data/raw/*.json              社媒+广告 │
│    ├ reddit                                                         │
│    ├ twitter (X)                                                    │
│    ├ fb_adlib (Meta 广告)                                            │
│    ├ iap_pricing                                                    │
│    └ appstore_rank / reviews / sensor_tower / androidrank            │
│  community_insights/       ─→ data/community_ai_analysis.json AI 派生│
│                                                                      │
└──────────────────────────────────────┬──────────────────────────────┘
                                       │ 7 大 JSON 源
                                       ▼
┌── 聚合层 ────────────────────────────────────────────────────────────┐
│  data_pipeline/aggregator.py     ─→ data/dashboard_data.json         │
│    ├ schema.py（统一 dataclass）                                      │
│    └ alert_engine.py（22 条预警触发器，配置见 alert_config.json）    │
└──────────────────────────────────────┬──────────────────────────────┘
                                       ▼
┌── 看板层 ────────────────────────────────────────────────────────────┐
│  main_dashboard/dashboard_server.py   HTTP API（v2 后端 :8899）      │
│  intel-ops-frontend/                  React + Vite 前端（:5173）     │
│                                                                      │
│  页面：总览看点 / 预警中心 / 排名异动 / 收入下载 / IAP / 网站数据 /    │
│        产品动态 / GP 评论 / 社媒 / 商业新闻 / 广告投放 / 候选发现     │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 快速启动

```bash
# 1. 第一次配置密钥
cp .env.local.example .env.local
# 用编辑器打开 .env.local 填入 CLAUDE_API_KEY 等

# 2. 一键启动看板（自动加载 .env.local）
./启动看板.command
# 浏览器自动打开 http://localhost:8899
```

启动器会显示当前 key 配置状态（`已配置` / `未配置`），不打印 key 值。

---

## 核心改动 v2（最近重构）

### 1. AI 配置统一

所有模型 / Prompt / 节点 / 阈值集中在 [`config/ai_tasks.json`](config/ai_tasks.json)。
业务代码只调 `run_task("name", context)` — 不再硬编码模型、URL、retries。

详见 [`config/README.md`](config/README.md)。

| 层 | 文件 | 内容 |
|---|---|---|
| Endpoints | `ai_tasks.json::endpoints` | `flashapi`（中转） + `anthropic_official`（官方备用） |
| Models | `ai_tasks.json::models` | `haiku_4_5` / `sonnet_4_6` / `opus_4_6` / `monetize_tag` |
| Tasks | `ai_tasks.json::tasks` | 11 个 AI 任务，每个绑定 model + prompt + format |

**自动 fallback**：中转 5xx/429 时自动切官方端点。

### 2. 密钥外置

| 项 | 位置 | git 跟踪 |
|---|---|---|
| Key 实际值 | `.env.local`（项目根，gitignored） | ❌ |
| Key 模板 | `.env.local.example` | ✅ |
| 配置中只引用变量名 | `ai_tasks.json::api_key_env: "CLAUDE_API_KEY"` | ✅ |

支持的 key：`CLAUDE_API_KEY` / `ANTHROPIC_API_KEY` / `X_BEARER_TOKEN`。

启动器和 `dashboard_server.py` 都会自动 `load_env_file()` 加载 `.env.local`。

### 3. 统一抓取流（7 脚本并行）

总览顶部"同步数据"按钮一键并行 7 个抓取：

```
strategy_monitor / market_rank / daily_report / commercial_strategy /
fb_adlib / reddit_crawl / twitter_crawl
        │
        ▼ Promise.all 并行（任一失败不阻塞）
        ▼
data_pipeline.aggregator（聚合 dashboard_data.json + 重算预警）
        │
        ▼
增量刷新前端（不重载页面）+ 进度文案 + Toast 通知
```

### 4. 预警引擎

[`data_pipeline/alert_engine.py`](data_pipeline/alert_engine.py) — 22 条触发器集中：

- 排名跳变 / 周对比 / 基线偏离
- 评论负面爆发 / 占比 / 体量
- 社媒情绪占比 / AI alert level / 痛点严重度
- 产品更新爆发 / bugfix 集中
- 广告投放异常 / 节奏 z-score
- IAP 价格 / 收入漂移
- 下载日 / 周突变

阈值配置：[`data/alert_config.json`](data/alert_config.json)（自动生成默认值，可手改）。

### 5. 总览看板 4 层金字塔

```
L0 一眼态势   ─ 综合健康度 / 高风险数 / 新机会数 / 行业脉搏 sparkline
L0.5 预警精华 ─ 最高 severity 一条 + 共 N 条
L1 模块 KPI   ─ 5 张迷你看板（排名 / 产品 / 评论 / 社媒 / 商业）
L2 横切对比   ─ 战况表（多维排序） + 风险机会 2x2 矩阵
L3 信号流     ─ 时间轴 + 痛点机会 Top5
```

### 6. AI 触发按钮（per-page）

| 页面 | 按钮 | 后端 |
|---|---|---|
| 评论周报 | "重新生成" | `weekly_review.py` |
| 商业分析 | "生成周报" | `commercial_strategy --weekly` |
| 商业分析（弹窗） | "AI 策略分析" | `POST /api/ai/ads-strategy` |
| 社媒舆情（per comp） | "启动 AI 分析" / "重新分析" | `POST /api/ai/community-insights` |
| 社媒舆情（汇总） | "批量分析（N 个未生成）" | 串行触发上述 |
| 竞品详情 | "运行分析"（功能深度） | `competitor_detail.py` |
| 竞品详情 | "生成 3 日评论 AI"（NEW） | `review_3d_summary.py` |

---

## 目录速查

```
config/
  ai_tasks.json       AI 模型/任务/节点（核心配置）
  README.md           AI 配置说明（详细）

shared/
  ai_client.py        run_task 统一入口
  env_loader.py       .env.local 加载（零依赖）

prompts/
  comment_prompts.py  评论类 prompt builder
  community_prompts.py 社媒
  ads_prompts.py      广告

data_pipeline/
  schema.py           统一 dataclass（Alert / Snapshot / Reviews / …）
  aggregator.py       7 源 → dashboard_data.json
  alert_engine.py     22 条预警触发器

main_dashboard/
  dashboard_server.py 后端 HTTP API（:8899，v2 仅做 REST API）

intel-ops-frontend/      React 18 + Vite 5 + TS 前端（:5173）

data/
  dashboard_data.json 唯一聚合产物（前端消费）
  alert_config.json   预警阈值配置
  *.json              各采集模块产物（多数 gitignored）
  raw/                async_crawler 的原始抓取（gitignored）

.env.local            密钥（gitignored，永不提交）
.env.local.example    密钥模板（提交）
启动看板.command      启动器（已去硬编码，从 .env.local 加载）
```

---

## 常见操作

### 改 AI 模型 / Prompt

完全不动业务代码。详见 [`config/README.md`](config/README.md)。

```bash
# 看某个 task 的实际生效配置（合并 endpoint + model + task + env）
python3 -m shared.ai_client review_3d --explain

# 临时调温度
export AI_OVERRIDE__review_3d__temperature=0.7
```

### 单独跑某模块

```bash
# 抓取
python3 strategy_monitor/run_headless.py
python3 market_rank/run_headless.py
python3 competitor_comment/auto_report.py
python3 commercial_strategy/run_headless.py
python3 -m async_crawler --sources reddit,twitter,fb_adlib

# AI 分析（per competitor）
python3 competitor_comment/competitor_detail.py SofaScore --days 7
python3 competitor_comment/review_3d_summary.py SofaScore --days 3
python3 competitor_comment/weekly_review.py
python3 competitor_comment/run_all_details.py

# 看板（v2：双击启动看板.command 同时拉起 backend + vite）
bash 启动看板.command
# 或分别：
python3 main_dashboard/dashboard_server.py 8899   # backend
cd intel-ops-frontend && npm run dev               # frontend :5173
```

### 同步数据

```bash
# 全部抓取 + 聚合（手动）
python3 scripts/daily_sync.py
python3 -m data_pipeline.aggregator   # 单独重新聚合
```

---

## 外部依赖

- Python 3.10+（stdlib + `aiohttp`）
- API：[flashapi.top](https://ai.flashapi.top/v1/messages) 中转 / 可选 [api.anthropic.com](https://api.anthropic.com/v1/messages) 官方
- macOS（`启动看板.command` 是 bash），Linux/WSL 可手动 `python3 main_dashboard/dashboard_server.py`

---

## 数据 / 文件 git 政策

| 类型 | 路径 | git |
|---|---|---|
| 源码 + 配置模板 | `*.py` / `config/*.json` / `.env.local.example` | ✅ |
| 主索引 | `data/competitors.json` / `data/regions.json` | ✅ |
| 运行产物 | `data/*.json`（除上 2 个）/ `data/raw/` / `competitor_comment/reports/*.md` | ❌ |
| 生成产物 | `main_dashboard/dashboard.html` | ❌ |
| 密钥 | `.env` / `.env.local` / `.env.*.local` | ❌ |
| 缓存 | `__pycache__/` / `.DS_Store` / `.claude/` | ❌ |

---

## 安全

- ⚠️ **永远不要**把 key 写进任何 `*.py` / `*.json` / `*.command` 文件
- ✅ 只通过 `.env.local`（gitignored）或浏览器顶部 API Key 框输入
- ✅ 密钥泄露处置：去 [flashapi 控制台](https://ai.flashapi.top) 或 [anthropic 控制台](https://console.anthropic.com/settings/keys) 撤销旧 key + 申请新 key
- ✅ 历史已用 `git filter-repo` 清洗过，旧硬编码 key 不再存在于任何 commit 中
