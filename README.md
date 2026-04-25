# INTEL-OPS

INTEL-OPS 是一个面向足球/体育 App 的竞品情报平台，统一监控 App Store 和 Google Play 上的竞品评论、排名变化、版本更新和商业化动作，并把结果汇总到 HTML 看板。

## 当前结构

四个采集模块通过 `data/` 目录解耦，主看板只读取 JSON 结果：

```text
competitor_comment/   -> data/competitor_comments.json, weekly_review.json, competitor_detail_*.json
strategy_monitor/     -> data/strategy_monitor.json, strategy_state.json
market_rank/          -> data/market_rank.json, ranking_history.json
commercial_strategy/  -> data/commercial_strategy.json, commercial_weekly.json, commercial_history.json
main_dashboard/       -> 读取 data/*.json，生成 dashboard.html，并提供 HTTP API
```

## 配置约定

- 竞品注册表只保留一份：`data/competitors.json`
- 地区配置只保留一份：`data/regions.json`
- 评论分析类 prompt 统一维护在 `prompts/comment_prompts.py`

## 评论分析现状

- 滚动评论监测：抓近 3 天全量评论，不再只抓差评
- 评论周报：按 `competitors.json` 和 `regions.json` 动态生成 prompt
- 竞品详情页：支持单竞品深度分析和批量分析全部竞品
- 评论标签已切换为信号型分类：
  - `[问题抱怨]`
  - `[高价值功能请求]`
  - `[竞品对比]`
  - `[流失信号]`
  - `[正向反馈]`
  - `[其他]`

## 运行方式

```bash
# 一键启动
./启动看板.command

# HTML 看板服务
python3 main_dashboard/dashboard_server.py

# 只生成静态看板
python3 main_dashboard/generate_dashboard.py

# 采集/分析
python3 competitor_comment/auto_report.py
python3 competitor_comment/weekly_review.py
python3 competitor_comment/competitor_detail.py SofaScore --days 7
python3 competitor_comment/run_all_details.py
python3 strategy_monitor/run_headless.py
python3 market_rank/run_headless.py
python3 commercial_strategy/run_headless.py
python3 commercial_strategy/run_headless.py --weekly
```

## 外部依赖

- 环境变量：`CLAUDE_API_KEY`
- AI API：`https://ai.flashapi.top/v1/messages`
- 核心依赖：`streamlit`, `pandas`, `plotly`, `requests`, `google-play-scraper`

## 数据说明

- `data/competitors.json`、`data/regions.json` 应纳入版本管理
- `data/*.json` 其余大多属于运行产物
- `main_dashboard/dashboard.html` 属于生成产物，不应手改
- `competitor_comment/reports/*.md` 属于历史报告产物

## 推荐版本管理方式

这个项目最适合用 Git 做“源码与配置入库、运行产物忽略”的管理方式：

1. 跟踪源码和配置
   - 跟踪 `competitor_comment/`, `strategy_monitor/`, `market_rank/`, `commercial_strategy/`, `main_dashboard/`, `prompts/`
   - 跟踪 `data/competitors.json` 和 `data/regions.json`

2. 忽略运行产物
   - 忽略 `__pycache__/`, `.DS_Store`
   - 忽略运行生成的 `data/*.json`
   - 但保留 `data/competitors.json` 和 `data/regions.json`
   - 忽略 `main_dashboard/dashboard.html`
   - 忽略 `competitor_comment/reports/*.md`

3. 建议提交节奏
   - 配置变更单独提交，例如“调整监控地区”或“新增竞品”
   - 功能改动单独提交，例如“评论分析切换为全量评论抓取”
   - 生成产物不要混在功能提交里

4. 建议分支规则
   - `main`：稳定可运行版本
   - `feature/*`：功能开发
   - `fix/*`：缺陷修复
   - `ops/*`：配置或监控口径调整

5. 建议提交信息
   - `feat: 评论分析改为全量评论抓取`
   - `fix: 统一 competitors.json 为唯一竞品配置源`
   - `chore: 清理缓存并补充 gitignore`
   - `docs: 重写项目 README`

## 当前建议

如果你准备正式开始做版本管理，下一步最合适的是：

```bash
git init
git add .
git commit -m "chore: initialize INTEL-OPS repository"
```

提交前建议先确认 `.gitignore` 已经排除了运行产物，避免把实时数据快照一并提交进去。
