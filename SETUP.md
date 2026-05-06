# INTEL-OPS 新机器初始化指南

> 在一台几乎全新的 macOS / Linux 电脑上，从零跑起这个看板。
> 全程预计 **15–25 分钟**（不含 API key 申请）。

---

## 一、系统要求

| 项 | 最低 | 推荐 |
|---|---|---|
| **OS** | macOS 12+ / Ubuntu 20.04+ / Windows WSL2 | macOS 14+ |
| **Python** | 3.10 | 3.11 或 3.12 |
| **磁盘** | 500 MB（含依赖） | 1 GB |
| **网络** | 必须能访问 Apple iTunes / Google Play / Reddit / Sensor Tower | 全球可达 |

> Windows 直接跑会有 SSL / shell 兼容问题，**强烈建议 WSL2**。

---

## 二、零步骤总览

```
1. 装 Python 3.10+ + git                       ~5 min
2. clone 仓库                                  ~1 min
3. 装 Python 依赖                              ~5 min
4. 创建 .env.local 填 API key                   ~5 min（含申请）
5. 双击 启动看板.command 跑起来                  ~30 sec
6. 浏览器打开 → 点"同步数据"拉真数据              ~3-5 min
```

---

## 三、详细步骤

### 1. 装系统依赖

#### macOS

```bash
# 1.1 装 Xcode 命令行工具（含 git）
xcode-select --install

# 1.2 装 Homebrew（如还没装）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 1.3 装 Python 3.11+
brew install python@3.11

# 验证
python3 --version    # 期望 ≥ 3.10
```

#### Ubuntu / Debian

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git curl
python3 --version
```

#### Windows (WSL2)

参考 [Microsoft 官方指南](https://learn.microsoft.com/en-us/windows/wsl/install) 装好 WSL2 + Ubuntu，然后跟 Ubuntu 步骤。

---

### 2. Clone 仓库

```bash
cd ~/Desktop                                    # 或任意位置
git clone <你的仓库 URL> Football_Intel_Suite
cd Football_Intel_Suite
```

> 私有仓库需先配 SSH key 或用 PAT。

---

### 3. 装 Python 依赖

**推荐方式：用户级安装（避免污染系统 Python）**

```bash
# macOS Homebrew Python 14+ 需 --break-system-packages（PEP 668）
pip3 install --user --break-system-packages \
  aiohttp \
  google-play-scraper \
  app-store-scraper \
  pandas \
  requests \
  beautifulsoup4
```

**或用 venv（更干净，推荐）**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install \
  aiohttp \
  google-play-scraper \
  app-store-scraper \
  pandas \
  requests \
  beautifulsoup4
```

> 启动看板.command 用的是系统 `python3`。如果用 venv，要么改 .command 里的 `python3` 为 `.venv/bin/python3`，要么每次启动前 `source .venv/bin/activate`。

#### 依赖清单（按用途）

| 包 | 用途 | 必需 / 可选 |
|---|---|---|
| `aiohttp` | async_crawler 异步抓取（fb_adlib / reddit / twitter / iap_pricing） | **必需** |
| `google-play-scraper` | Google Play 评论抓取（auto_report / weekly_review / competitor_detail） | **必需** |
| `app-store-scraper` | App Store 评论备用 | 可选（iTunes RSS 已够用） |
| `pandas` | market_rank 表格处理 | **必需** |
| `requests` | strategy_monitor / market_rank HTTP 调用 | **必需** |
| `beautifulsoup4` | 部分 HTML 解析备用 | 可选 |

> **最小集**（跑看板 + 同步抓取够）：`aiohttp + google-play-scraper + pandas + requests`

---

### 4. 配置 API Key

```bash
cp .env.local.example .env.local
# 用任意编辑器打开
nano .env.local        # 或 vim / code .env.local
```

填入这些 key：

```bash
# === 必填（至少其一）===

# Claude API 中转代理（推荐 — 国内更稳）
CLAUDE_API_KEY=sk-xxxxxxxx...

# 或 Anthropic 官方
ANTHROPIC_API_KEY=sk-ant-xxxx...


# === 可选 ===

# X (Twitter) v2 Bearer Token
# 不填：社媒抓取自动跳过 X 源
# 申请：https://developer.x.com → Apps → Keys and tokens → Bearer Token
X_BEARER_TOKEN=AAAA...

# Meta 广告库 Access Token
# 不填：Meta 广告抓取大概率被反爬
# 申请：https://developers.facebook.com/tools/explorer/
#   → 选 App → Get User Access Token → 勾 ads_read
META_AD_LIBRARY_TOKEN=EAA...
```

> **`.env.local` 已在 `.gitignore`，绝不会提交。**

#### 申请 Claude API Key

- **方案 A · 中转（推荐）**：联系内部管理员拿 flashapi.top 的 key（开头 `sk-...`）
- **方案 B · 官方**：https://console.anthropic.com → API Keys → Create Key

#### 申请 X Bearer Token（10 分钟）

1. https://developer.x.com → 登录 → Sign up for Free Account
2. 创建 Project + App
3. App settings → Keys and tokens → Bearer Token → Generate

#### 申请 Meta Token（10 分钟）

1. https://developers.facebook.com/apps/ → Create App → Other
2. Add Product → Ad Library API
3. Tools → Graph API Explorer → 选 App → Get User Access Token → 勾 `ads_read`
4. Tools → Access Token Debugger → "Extend Access Token"（拿 60 天版本）

---

### 5. 首次启动

```bash
# 给启动脚本执行权限
chmod +x 启动看板.command

# 启动
./启动看板.command
```

期望输出：

```
✅ 服务器已启动 (PID: xxxxx)
   - 中转 key:  已配置
   - 官方 key:  未配置
   - X token:   已配置
```

浏览器自动开 http://localhost:8899

> **首次启动前，data/ 目录下会有一些样本 fixture（已 commit），可以直接看到看板效果。要拉真实数据，点页面顶部"同步数据"按钮。**

---

### 5b. Playwright 持久登录态（一次性手动登）

下面 4 个抓取器走 Playwright 持久 profile，**首次必须手动登录一次**（cookie 存盘后续自动用，失效再重登）：

| 抓取器 | 一次性登录命令 | 登录页 | 登录方式 |
|---|---|---|---|
| **qimai IAP**（替代 Apple HTML，绕开 IP redirect 到 CN 的死结） | `python3 -m market_rank.scrape_qimai_iap login` | qimai.cn 首页 | 手机号 / 微信 / 账号 |
| AppMagic | `python3 -m market_rank.scrape_appmagic login` | appmagic.rocks | 免费账号 |
| Sensor Tower | `python3 -m market_rank.scrape_sensor_tower login` | sensortower.com | 免费账号 |
| Meta Ad Library | `python3 -m market_rank.scrape_fb_adlib login` | facebook.com/ads/library | FB 账号 |

**qimai 登录的额外注意**（反爬绕过）：
- 我们用**系统 Google Chrome** 而不是 Playwright bundled chromium（关掉 `AutomationControlled` flag）
- 弹窗打开后**只在首页操作**，不要点 app 链接（点错跳到详情页未登录态会被 SPA 弹 /404，那是 qimai 反爬正常行为）
- 在 qimai.cn 首页右上角点「登录」 → 完成验证 → 看到自己的头像/昵称才算登录成
- 回终端按 Enter 保存 cookie 到 `~/.qimai-profile/state.json`

如果新登的还 404，重新跑 `login` 命令——cookie 失效或 qimai 换了反爬规则，可能要再加 stealth 措施。

---

### 6. 首次同步数据

1. 浏览器顶部点 "**同步数据**" 按钮
2. 进度条显示 `(N/8)：标签`
3. 等 3-5 分钟全部完成
4. 总览页底部 "**同步抓取日志**" 卡可看每步耗时 / 失败详情

期望成果：
- 产品动态卡：6 个竞品的发布时间填好
- 排名页：top 100 全有 + 监测竞品有 14 天历史
- 用户评论页：6 个竞品都有评论
- 商业页：IAP 价格 + Sensor Tower 收入数据
- 社媒页：Reddit 帖子（如 X token 已配，含 X）

---

## 四、目录结构

```
Football_Intel_Suite/
├── .env.local              # API key 配置（gitignored，自己创建）
├── .env.local.example      # 模板
├── 启动看板.command         # macOS 双击启动
├── SETUP.md                # 本文档
│
├── data/                   # 所有数据（部分 gitignored）
│   ├── competitors.json    # 监测竞品配置（必需）
│   ├── regions.json        # 地区配置
│   ├── dashboard_data.json # 聚合产物（自动生成）
│   ├── sync_log.json       # 同步日志（自动生成）
│   ├── alert_config.json   # 预警阈值（自动生成）
│   └── raw/                # 抓取产物
│
├── main_dashboard/
│   └── dashboard_server.py       # v2 REST API（:8899）
│
├── intel-ops-frontend/           # React + Vite 前端（:5173）
│
├── data_pipeline/
│   ├── aggregator.py        # 7 数据源 → 统一 dashboard_data.json
│   ├── alert_engine.py      # 23 条预警触发器
│   └── schema.py            # 数据结构定义
│
├── async_crawler/           # 异步抓取（fb / reddit / twitter / iap）
├── market_rank/             # iTunes 体育榜 + sensor_tower
├── strategy_monitor/        # iTunes 版本监测
├── competitor_comment/      # 评论抓取 + 周报 + 详情分析
├── commercial_strategy/     # 商业策略 / IAP 定价
├── community_insights/      # 社媒 AI 分析
├── prompts/                 # AI prompt 模板
├── shared/                  # 共享工具（env_loader 等）
└── config/                  # AI / Alert 配置
```

---

## 五、常见故障

### 1. `ModuleNotFoundError: No module named 'aiohttp'`

```bash
pip3 install --user --break-system-packages aiohttp
```

### 2. `❌ 缺少 .env.local`

```bash
cp .env.local.example .env.local
# 编辑填 key
```

### 3. 端口 8899 被占用

```bash
lsof -ti:8899 | xargs kill -9
./启动看板.command
```

### 4. 同步失败，怎么排查

打开浏览器看 **同步抓取日志卡**（总览页底部）：
- ✗ 红色行 → 点击展开看 stderr
- 常见错误：
  - `HTTP 429`：API 限流，等几分钟重试
  - `403 Client challenge`：Meta 反爬，需配 META_AD_LIBRARY_TOKEN
  - `超时（1200秒）`：网络慢，单独跑该脚本看进度
  - `ModuleNotFoundError`：装依赖

### 5. 想 SSL 证书校验跳过

部分企业网络拦截 SSL，脚本里多数 `urlopen` 已加 `ssl.CERT_NONE` 跳过。如仍报错：

```python
# 检查 ~/.python-eggs/ 或 SSL 证书路径
# 或临时：export PYTHONHTTPSVERIFY=0
```

### 7. Sensor Tower 一直 429

新代码已加退避重试（5/10/20/40s）。如仍失败，等 1 小时再试 — 它的公开 API 有 IP 级限制。

---

## 六、最小 / 最大依赖矩阵

### 最小可跑（仅看板 + 评论 + 排名）

```
aiohttp + google-play-scraper + pandas + requests
+ CLAUDE_API_KEY
```

不能用：Meta 广告 / X 社媒 / Streamlit UI

### 全功能

```
aiohttp + google-play-scraper + app-store-scraper +
pandas + requests + beautifulsoup4
+ CLAUDE_API_KEY + X_BEARER_TOKEN
```

---

## 七、第二天用法

```bash
cd ~/Desktop/Football_Intel_Suite
./启动看板.command
```

浏览器自动打开 http://localhost:8899，点"同步数据"刷新。

---

## 八、卸载 / 重装

```bash
# 1. 停服务
pkill -9 -f dashboard_server.py

# 2. 删依赖（仅 venv 模式）
rm -rf .venv

# 3. 删数据（保留代码）
rm -rf data/raw data/dashboard_data.json data/sync_log.json
rm -rf data/competitor_detail_*.json data/review_3d_*.json

# 4. 完全删
cd ~/Desktop && rm -rf Football_Intel_Suite
```

---

## 九、需要进一步帮助

| 场景 | 怎么办 |
|---|---|
| 添加新竞品 | 编辑 `data/competitors.json`，加 `{name: {gp, ios, app_id, bundle_id}}`；用 `google_play_scraper.app(pkg)` 验证包名 |
| 修改预警阈值 | 编辑 `data/alert_config.json`（首次运行后自动生成） |
| 调整 AI prompt | 编辑 `prompts/*.py` 里对应的 builder 函数 |
| 改抓取频率 | 编辑 `async_crawler/sources/*.py` 里的 `rate_limit` |
| 看完整 API | http://localhost:8899/api/sync_log 等端点直接 curl |
