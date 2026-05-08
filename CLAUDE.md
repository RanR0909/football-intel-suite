# CLAUDE.md

写给以后接手这个仓库的 Claude / 工程师。要怎么跑、改东西碰哪儿、避哪些坑。

---

## 一句话

足球 / 体育 App 竞品情报系统。**抓 12 个数据源 → 写 MySQL+JSON → AI 分类标注 → alert 引擎判规则 → React 前端展示**。9 个竞品 + 1 个 baseline (AllFootball)，覆盖 12 区域。

---

## 启动

```bash
./启动看板.command         # 一键起 backend(:8899) + vite(:5173)，自动开浏览器
python3 scripts/daily_sync.py   # 手动拉一次数据（首次必跑，~15-30 分钟）
```

完整安装详见 [SETUP.md](SETUP.md)。

---

## 数据流

```
launchd cron (02:00)
   │
   ▼
scripts/daily_sync.py  ── 3-Phase 流水线
   │
   ├─ Phase 1（并行 ≤4 路）: 12 数据源抓取
   │     ├─ HTTP        : appstore_rank / androidrank / reddit / twitter / comment_fetch / app_versions / google_news
   │     └─ Playwright  : appmagic / fb_adlib (×5 国) / sensor_tower (ios+android) / qimai_iap
   │
   ├─ Phase 2（串行）   : AI 管道
   │     ├─ discover_peers   ── appstore_rank top 100 → app_classifier → app_classifications 表
   │     └─ ai_pipeline      ── comment_label + entity_extract + 7 类 alert 触发器
   │
   └─ Phase 3           : data_pipeline.aggregator → data/dashboard_data.json
        │
        ▼
main_dashboard/dashboard_server.py (:8899)
   │ 读 dashboard_data.json + 直查 MySQL（每请求重读，无缓存）
   ▼
intel-ops-frontend (vite :5173)  ── /api/* 走 vite proxy 转 :8899
```

每个抓取源结束都写 `shared/sync_state` 和 `data/sync_log.json` —— 前端 SyncStatusBar 30 秒轮询刷新状态。

---

## 模块速查

| 路径 | 干嘛 |
|---|---|
| `async_crawler/sources/` | 8 个 HTTP 抓取源（aiohttp + retry） |
| `market_rank/scrape_*.py` | 4 个 Playwright scraper（持久 profile 在 `~/.<name>-profile`） |
| `competitor_comment/comment_fetch.py` | GP + iOS 评论抓取（用 google-play-scraper + iTunes RSS） |
| `ai_tasks/` | AI 任务实现（comment_label / entity_extract / alert_title / app_classifier） |
| `prompts/` | 各 AI 任务的 prompt builder |
| `config/ai_tasks.json` | endpoints / models / tasks 三层配置（改这里换模型 / 调温度，不动代码）|
| `shared/ai_client.py` | `run_task("name", context)` 统一 AI 调用入口（urllib，零 SDK 依赖）|
| `shared/env_loader.py` | `.env.local` + `~/.intelops-secrets` 双层加载 |
| `shared/db.py` | SQLAlchemy session + Redis 客户端；`MYSQL_DSN` / `REDIS_URL` 任一缺失自动降级 |
| `shared/sync_state.py` | 各源 last_success / last_failure / consecutive_failures（前端状态条数据源）|
| `shared/retry_queue.py` | 失败任务指数退避队列（[5min, 30min, 2h, 6h, 12h]）|
| `data_pipeline/aggregator.py` | 7 源 → `dashboard_data.json` |
| `data_pipeline/alert_engine.py` | 7 类 alert 触发器（排名 / 评论 / 社媒 / 产品更新 / 广告 / IAP / 下载）|
| `main_dashboard/dashboard_server.py` | 纯 REST API（19 端点，stdlib http.server）|
| `intel-ops-frontend/src/hooks/api/` | TanStack Query hooks，每个 API 端点一个 |
| `intel-ops-frontend/src/pages/` | 14 个页面（Overview + AlertCenter + content/* + data/* + system/*）|
| `migrations/` | Alembic 数据库迁移 |
| `scripts/daily_sync.py` | 02:00 自动跑的主调度器 |
| `scripts/weekly_sync.py` | 周日 03:00 跑（IAP 价格 + Google News + 流量数据） |
| `launchd/*.plist` | launchd agent 模板（含 `__PROJECT_ROOT__` 占位符） |

---

## 端口 & 进程

| 端口 | 服务 | 起法 |
|---|---|---|
| 8899 | dashboard_server.py（纯 API） | `python3 main_dashboard/dashboard_server.py` |
| 5173 | vite dev server | `cd intel-ops-frontend && npm run dev` |
| 3306 | MySQL（可选）| `docker compose up -d` |
| 6379 | Redis（可选） | 同上 |

`vite.config.ts` 里 `host: "::"`（IPv4+IPv6 dual-stack）+ proxy `/api` → `127.0.0.1:8899`（写死 IPv4 因为 Node 18 默认 DNS 优先 IPv6 [::1] 而后端只监听 IPv4）。

---

## 改东西怎么动

### 加 / 删一个竞品
编辑 [data/competitors.json](data/competitors.json)：`{name: {gp, ios, app_id, bundle_id, website, is_baseline?}}`。用 `python3 -c "from google_play_scraper import app; print(app('PKG'))"` 验包名。

### 换 AI 模型 / 调 prompt
改 [config/ai_tasks.json](config/ai_tasks.json) 不用动代码。合并优先级：env override > 调用 overrides > task > model > endpoint。

### 加一个抓取源
1. 写 `async_crawler/sources/foo.py`（看 `appstore_rank.py` 模板）
2. 在 [scripts/daily_sync.py](scripts/daily_sync.py) `PHASE_1_FETCHERS` 加一行
3. 如果要前端展示：写 dao（`shared/dao_*.py` 模板）+ 在 [main_dashboard/dashboard_server.py](main_dashboard/dashboard_server.py) 加 `/api/foo` + 前端加 `useFoo.ts` hook + 卡片

### 加一类 alert
[data_pipeline/alert_engine.py](data_pipeline/alert_engine.py) 写一个 `_check_xxx` 函数，注册到 `_ALERT_RULES`。阈值放 [data/alert_config.json](data/alert_config.json)（首次跑会自动生成默认值）。

### 改 launchd 调度
编辑 [launchd/com.intelops.*.plist](launchd/) 里的 `StartCalendarInterval` / `StartInterval`，重跑 `bash scripts/install_launchd.sh`。

---

## 9 竞品 + 12 区域

竞品（`is_baseline: true` 的 AllFootball 是自家产品，参与抓取但前端展示分流）：
SofaScore / FlashScore / OneFootball / 365Scores / Fotmob / LiveScore / AiScore / BeSoccer / 310Scores / **AllFootball** (baseline)

区域：us / gb / de / fr / es / it / br / mx / ng / sa / ae / jp

---

## AI 任务（4 个，全 Claude Haiku 4.5）

| task | 输入 → 输出 | 触发 |
|---|---|---|
| `comment_label` | 评论 → `{language, translated_text, label}` (6 类：complaint / feature_request / competitor_compare / churn_signal / positive / other) | 日更 |
| `entity_extract` | 评论 → `[{type, raw_value, canonical_id}]`（9 类实体：球员 / 球队 / 联赛 / 赛事 / 功能 / 竞品 app / 平台 / 体育术语 / 其他）| 紧跟 comment_label |
| `alert_title` | metadata → `{title}` (≤50 字事实陈述) | alert_engine 命中后 |
| `app_classifier` | metadata → `{is_relevant, topic, categories, confidence}` | discover_peers 用，候选发现 |

所有 AI 调用都通过 `shared.ai_client.run_task` —— 不要绕过这层直接打 API。

---

## 数据 / 文件 git 政策

| 类型 | git |
|---|---|
| 源码 + 配置模板（`*.py` / `config/*.json` / `.env.local.example`） | ✅ |
| 主索引（`data/competitors.json` / `data/regions.json` / `data/market_history.csv`）| ✅ |
| 抓取产物（`data/*.json` 除上述 / `data/raw/`） | ❌ |
| 看板聚合产物（`dashboard_data.json` / `sync_log.json` / `alert_config.json`） | ❌ |
| 密钥（`.env.local`） | ❌ |
| Playwright cookies（`~/.<name>-profile`） | ❌（在用户 home 不在仓库）|

---

## 容易踩的坑

1. **launchd plist 模板有 `__PROJECT_ROOT__` 占位符** —— 必须用 `bash scripts/install_launchd.sh` 安装才会做 sed 替换，**不要直接 `cp` 进 LaunchAgents**。

2. **首次启动看板会全空白** —— `dashboard_data.json` 不在 git 里，要先跑 `python3 scripts/daily_sync.py` 生成。

3. **没有"同步数据"按钮** —— v2 把手动同步入口下线了，sync 只能从 launchd 或命令行触发。

4. **MYSQL_DSN / REDIS_URL 不配是 OK 的** —— dao 层会自动降级到 JSON-only，看板能正常显示主流数据；但失去历史趋势分析（评论 6 类标签历史 / 排名快照对比 / 收入历史）。

5. **Playwright scraper exit code 2 = LoginRequired** —— cookie 失效，要手动跑对应的 `login` 子命令重登。daily_sync 里有专门检测这个 exit code 触发飞书红卡。

6. **qimai 抓取必须用系统 Chrome** 不能用 Playwright bundled chromium（反爬识别 `AutomationControlled` flag）。代码里 `channel="chrome"`。

7. **Sensor Tower 限流是 IP 级**（不是 cookie 级）—— 持续 429 等 1 小时，没法绕。

8. **前端 staleTime = 60 秒**（[App.tsx](intel-ops-frontend/src/App.tsx)），sync 跑完最多 1 分钟前端能看到新数据；切路由 / 切 tab 都强制 refetch。

9. **dashboard_server.py 是 stdlib http.server**（不是 Flask/FastAPI），改路由要在 `do_GET` / `do_POST` 里加 `if path == ...` 分支。

10. **`shared/env_loader` 不覆盖已存在的 env var** —— 在 shell 里 export 过的优先于 `.env.local`，调试时容易一脸懵。

---

## 关键 spec

- AI 只做结构化工作（分类 / 抽取 / 翻译 / 短事实陈述），**不写长文 / 不主观判断 / 不给建议**。
- 所有 fact 表三路写：MySQL 主存 + JSON 中间快照 + Redis 实时镜像（可选）。
- 失败重试：HTTP 类本地 3 次 → 还失败入 `retry_queue`；Playwright 类直接入 retry_queue + 飞书红卡。
- 前端禁 emoji / 禁动画 / 禁渐变；表格 + 数字 + 短文本为主，黑白灰 + AF 绿（#00D616）。
