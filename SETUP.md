# INTEL-OPS 安装指南

新 Mac 上从 0 跑起来这套看板，整流程 15–25 分钟（不含 API key 申请）。

> Linux / WSL2 也能跑，但 `启动看板.command` 是 macOS bash 脚本；Linux 用户直接跑下面 §6 里的两条命令分别启 backend 和前端即可。

---

## 1. 系统要求

| 项 | 最低 | 推荐 |
|---|---|---|
| OS | macOS 12+ | macOS 14+ |
| Python | 3.10 | 3.11 / 3.12 |
| Node.js | 18 | 20 LTS |
| 磁盘 | 1 GB（含 Playwright Chromium） | 2 GB |
| 网络 | 能访问 Apple iTunes / Google Play / Reddit / Sensor Tower / qimai.cn | 全球可达 |

---

## 2. 装系统依赖

```bash
# Xcode 命令行工具（带 git）
xcode-select --install

# Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Python + Node
brew install python@3.11 node@20

# 验证
python3 --version    # ≥ 3.10
node --version       # ≥ 18
```

---

## 3. Clone 仓库

```bash
cd ~/Desktop                                   # 或任意位置
git clone <仓库 URL> Football_Intel_Suite
cd Football_Intel_Suite
```

---

## 4. 装 Python 依赖

```bash
pip3 install --user --break-system-packages -r requirements.txt

# Playwright 还要装浏览器内核 —— qimai 抓取走系统 Chrome 也行，
# 其他 3 个 scraper（appmagic / sensor_tower / fb_adlib）需要 chromium：
python3 -m playwright install chromium
```

> 推荐 venv：`python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`。
> 注意：用 venv 时 `启动看板.command` 调的是系统 `python3`，要么改脚本里的 `python3` 为 `.venv/bin/python3`，要么每次启动前 `source .venv/bin/activate`。

[requirements.txt](requirements.txt) 里 `pymysql` 和 `redis` 是可选 —— 不配 `MYSQL_DSN` / `REDIS_URL` 就用不上，dao 层会自动降级到 JSON-only 模式（看板照常显示，但少了一些历史趋势数据）。

---

## 5. 装前端依赖

```bash
cd intel-ops-frontend
npm install
cd ..
```

---

## 6. 配 API Key

```bash
cp .env.local.example .env.local
nano .env.local       # 或 vim / code
```

至少填一个 Claude key：

```bash
# 中转（推荐 — 国内更稳）
CLAUDE_API_KEY=sk-xxxxxx

# 或官方
ANTHROPIC_API_KEY=sk-ant-xxxx
```

可选 key（不填就跳过对应抓取源 / 通知，不影响其他流程）：

| 变量 | 影响 | 怎么拿 |
|---|---|---|
| `UTOOLS_AUTH_TOKEN` | X (Twitter) 抓取 | 详见 .env.local.example 顶部 cookie 提取步骤 |
| `MYSQL_DSN` | 历史 fact 表读写（评论 / 广告 / IAP / 排名 / 社媒）| `docker compose up -d` 起本地 MySQL；DSN 默认值已写在模板里可直接用 |
| `REDIS_URL` | sync_state / retry_queue 实时镜像 | 同上 docker-compose 起 Redis |
| `FEISHU_WEBHOOK_URL` | sync 完成 / cookie 失效 / 重试时飞书通知 | 飞书群 → 群机器人 → 自定义机器人 |

> `.env.local` 已 gitignored，绝不会提交。
> 想"换台 Mac 不用重填"：把同样的 key 写一份到 `~/.intelops-secrets`，`shared/env_loader.py` 会双层兜底加载。

---

## 7. 起服务

```bash
chmod +x 启动看板.command
./启动看板.command
```

期望看到：

```
✓ backend ready (PID xxxxx)
✓ vite ready    (PID xxxxx)
════════════════════════════════════════
  ✅ INTEL-OPS 已启动
  v2 前端:    http://127.0.0.1:5173/
  v2 后端 API: http://127.0.0.1:8899/
════════════════════════════════════════
```

浏览器自动打开 http://localhost:5173/overview。Ctrl+C 停两个服务。

**Linux / WSL2 用户**：

```bash
# 终端 A
python3 main_dashboard/dashboard_server.py 8899

# 终端 B
cd intel-ops-frontend && npm run dev
# 浏览器开 http://localhost:5173/overview
```

---

## 8. 第一次拉数据

仓库里只 commit 了 3 个种子文件（`competitors.json` / `regions.json` / `market_history.csv`），首次启动看板看不到任何真实数据。**手动跑一次同步** 生成 `dashboard_data.json`：

```bash
python3 scripts/daily_sync.py
```

第一次大约 15–30 分钟（评论抓取 9 竞品 × 12 区是大头）。跑完看板就有数据了。

如果有源失败：打开 [系统 → 同步日志](http://localhost:5173/system/sync-log) 看 stderr。

---

## 9. Playwright 持久登录态（一次性）

下面 4 个抓取器走 Playwright 持久 profile，**首次必须手动登录一次**（cookie 落盘后续自动用，失效再重登）：

| 抓取器 | 一次性登录命令 | profile 路径 |
|---|---|---|
| AppMagic | `python3 -m market_rank.scrape_appmagic login` | `~/.appmagic-profile` |
| Sensor Tower | `python3 -m market_rank.scrape_sensor_tower login` | `~/.sensortower-profile` |
| Meta 广告库 | `python3 -m market_rank.scrape_fb_adlib login` | `~/.meta-adlib-profile` |
| qimai IAP（cn 区 IAP 价格）| `python3 -m market_rank.scrape_qimai_iap login` | `~/.qimai-profile` |

**qimai 反爬注意**：用系统 Chrome（`channel='chrome'`）而不是 bundled chromium，弹窗后只在 qimai.cn 首页操作，登录后回终端按 Enter 保存。

---

## 10. 装 launchd 自动同步（可选）

让 daily / weekly / retry 三个任务自动跑：

```bash
bash scripts/install_launchd.sh
```

| Agent | 调度 | 跑什么 |
|---|---|---|
| `com.intelops.daily` | 每天 02:00 | `daily_sync.py`（12 数据源 + AI 管道 + 聚合）|
| `com.intelops.weekly` | 周日 03:00 | `weekly_sync.py`（IAP 价格 + Google News + sitedata 流量）|
| `com.intelops.retry` | 每小时 | `daily_sync.py --retry-only`（清重试队列）|

> install 脚本会自动把 plist 模板里的 `__PROJECT_ROOT__` 替换成当前仓库路径 —— 换电脑 / 换用户名重跑这一行就行。

```bash
launchctl list | grep intelops    # 查状态
tail -f /tmp/intelops-daily.log    # 看最近一次跑的日志
bash scripts/uninstall_launchd.sh  # 卸
```

---

## 11. 起 MySQL + Redis（可选 · 推荐）

不配也能跑，但配上能存历史趋势（评论标签 / 排名快照 / 收入历史）。

```bash
# 装 docker desktop（一次性）
brew install --cask docker
open -a Docker        # 启动 Docker Desktop，等托盘图标变绿

# 起服务
docker compose up -d

# 验证
docker compose ps     # 看 mysql + redis 都是 Up
```

`.env.local.example` 里默认 DSN 已经匹配 `docker-compose.yml`，不用改。

---

## 12. 第二天怎么用

```bash
cd ~/Desktop/Football_Intel_Suite
./启动看板.command
```

如果装了 launchd，数据每天 02:00 自动更新；不装就手动 `python3 scripts/daily_sync.py`。

前端面板 60s 内会自动拉最新数据（TanStack Query staleTime + refetchOnMount），不用手动刷。

---

## 13. 常见故障

| 症状 | 排查 |
|---|---|
| `ModuleNotFoundError: No module named 'X'` | `pip install -r requirements.txt` |
| `❌ 缺少 .env.local` | `cp .env.local.example .env.local` 编辑填 key |
| 端口 8899 / 5173 被占 | `lsof -ti:8899 \| xargs kill -9` |
| Playwright 任务报 `LoginRequired` | 重新跑对应的 `login` 命令（cookie 失效）|
| qimai 登录后 404 | 反爬规则可能更新，重新登录；只在 qimai.cn 首页操作不要点 app 链接 |
| 同步失败查原因 | http://localhost:5173/system/sync-log 看 stderr / http 状态码 |
| 前端面板数据看起来旧 | 切换路由 / Cmd+R / 等 60 秒（staleTime 到期）|
| `dashboard_data.json` 不存在 | 跑一次 `python3 scripts/daily_sync.py` 生成 |
| Sensor Tower 持续 429 | 等 1 小时（IP 级限流）|

---

## 14. 完全卸载

```bash
# 停服务
pkill -9 -f dashboard_server.py
bash scripts/uninstall_launchd.sh

# 删数据（保留代码）
rm -rf data/raw data/dashboard_data.json data/sync_log.json
rm -rf data/competitor_detail_*.json data/review_3d_*.json

# Playwright cookies
rm -rf ~/.appmagic-profile ~/.sensortower-profile ~/.meta-adlib-profile ~/.qimai-profile

# 整个删
cd ~/Desktop && rm -rf Football_Intel_Suite
```
