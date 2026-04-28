# AI 模型配置说明

所有 AI 调用走统一入口，配置集中在 [`config/ai_tasks.json`](./ai_tasks.json)。改配置不用动代码。

---

## 三层结构

| 层 | 字段 | 职责 | 例 |
|---|---|---|---|
| **endpoints** | `url` / `api_key_env` / `verify_ssl` / `extra_headers` | API 端点（中转 / 官方） | `flashapi`, `anthropic_official` |
| **models**    | `name` / `endpoint` / `max_tokens` / `temperature` / `timeout` / `retries` / `fallback_endpoint` | 模型版本 + 调参 + 容灾 | `haiku_4_5`, `sonnet_4_6`, `opus_4_6` |
| **tasks**     | `model` / `prompt` / `output_format` | 业务任务用哪个模型 + 哪个 prompt | `review_3d`, `weekly_review_report`, … |

合并优先级（高 → 低）：`env override > 调用时 overrides > task > model > endpoint`

---

## 当前默认分配（速度优先）

| 模型 | 速度 | 用在哪 |
|---|---|---|
| **haiku 4.5** | ~1–3s | `comment_label` / `comment_daily_summary` / `review_3d` / `commercial_monetize_tag` / `commercial_intent` / `ads_strategy` / `community_insights` |
| **sonnet 4.6** | ~10–20s | `weekly_review_report` / `weekly_review_localization` / `competitor_detail` / `commercial_weekly` |
| **opus 4.6** | ~30–60s | （未启用，需要时手动切） |

---

## API Key 填哪

`.env.local`（项目根，gitignored，永不提交）：

```bash
CLAUDE_API_KEY=sk-...           # flashapi 中转（默认）
ANTHROPIC_API_KEY=sk-ant-...    # 官方备用（fallback）
X_BEARER_TOKEN=...              # X 抓取（可选）
GOOGLE_API_KEY=...              # Google CSE（商业新闻，可选）
GOOGLE_CSE_ID=...               # Google CSE 引擎 ID（同上）
```

首次：`cp .env.local.example .env.local` 然后编辑。

### 抓取源 Key 速查

| 源 | 需要的 Key | 未配置时 | 申请入口 |
|---|---|---|---|
| Reddit / iOS / GP / Androidrank | 无 | 正常跑 | — |
| X (Twitter) | `X_BEARER_TOKEN` | 整源跳过 | https://developer.x.com → Apps → Bearer Token |
| Meta 广告库（Playwright） | 无（手动登录） | — | `python3 -m market_rank.scrape_fb_adlib login` |
| Sensor Tower（Playwright） | 无（手动登录） | — | `python3 -m market_rank.scrape_sensor_tower login` |
| AppMagic（Playwright） | 无（手动登录） | — | `python3 -m market_rank.scrape_appmagic login` |
| **Google CSE（商业新闻）** | `GOOGLE_API_KEY` + `GOOGLE_CSE_ID` | 整源跳过（warning，不报错） | 见下 |
| **飞书机器人通知** | `FEISHU_WEBHOOK_URL` + `FEISHU_KEYWORD` | 所有通知静默跳过 | 见下 |

### Google CSE 申请步骤

1. **API Key**：
   - 进 https://console.cloud.google.com/apis/credentials
   - 创建项目（或用已有的）→ "Enable APIs" → 搜 "Custom Search API" 启用
   - "Credentials" → "Create credentials" → "API key" → 复制
2. **CSE ID（cx）**：
   - 进 https://programmablesearchengine.google.com/
   - "Add" 创建搜索引擎，"Search the entire web" 选 ON
   - 创建后复制 "Search engine ID"（形如 `017576662512468239146:omuauf_lfve`）
3. 填进 `.env.local` 的 `GOOGLE_API_KEY` / `GOOGLE_CSE_ID`
4. 跑：`python3 -m async_crawler --sources google_news` 或 dashboard 的"Google 商业新闻抓取"按钮

**配额**：免费 100 query/day，目前消耗 9（每竞品 1 query），冗余够。

### 飞书机器人配置

1. **创建群机器人**：
   - 打开飞书群（建议专门建一个 "INTEL-OPS 通知" 群）
   - 群设置 → **群机器人** → **添加机器人** → **自定义机器人**
   - 起名（如 "INTEL-OPS"），选图标
2. **安全设置**（任选其一）：
   - **关键词**（推荐）：填 `INTEL-OPS` — 简单，所有发出的消息会自动带这个前缀
   - 签名校验 / IP 白名单不推荐（本地 Mac 设置麻烦）
3. **复制 Webhook URL** → 填进 `.env.local`：
   ```bash
   FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx-xxxx
   FEISHU_KEYWORD=INTEL-OPS
   ```
4. **手动测试**：
   ```bash
   python3 -m shared.feishu_notify "测试消息"
   ```
   群里应立刻收到一条测试卡片。

### 飞书通知触发时机

| 场景 | 时机 | 卡片颜色 |
|---|---|---|
| 每日抓取完成 | daily_sync 结尾（02:00） | 全成功 → 绿；1-2 失败 → 橙；3+ 失败 → 红 |
| 周更完成 | weekly_sync 结尾（周日 03:00） | 同上 |
| Cookie 失效 | 任意 Playwright 源失败时**即时** | 红 |
| 重试队列处理 | 每小时 retry-only 实际处理过任务时 | 全成功 → 绿；有失败 → 橙 |
| 总耗时 > 30 min | daily_sync 结尾 | macOS 通知（飞书不发） |

未配置 `FEISHU_WEBHOOK_URL` 时所有飞书通知静默跳过，不影响主流程。

---

## 数据库（MySQL + Redis）

**主存储**：MySQL（评论 / 广告 / IAP / 排名 / 社媒 / sync_log，6 张事实表 + 2 张 lookup）
**缓存**：Redis（sync_state / retry_queue / sync_log:recent 镜像）
**JSON**：保留作 dashboard 主读路径 + DB 不可用时的 fallback（双写策略）

未配置 → dao 层降级 JSON-only，dashboard 顶部"数据库健康"卡片显示"未配置"。

### 第一次启动（开发期）

```bash
# 1. 装 Docker Desktop（如未装）
#    https://www.docker.com/products/docker-desktop/

# 2. 起 MySQL + Redis
cd /path/to/Football_Intel_Suite
docker compose up -d
docker compose ps      # 两个服务 healthy

# 3. 装 Python 依赖
pip3 install --break-system-packages -r async_crawler/requirements.txt

# 4. 在 .env.local 添加 DSN
echo 'MYSQL_DSN=mysql+pymysql://intelops:dev@localhost:3306/football_intel?charset=utf8mb4' >> .env.local
echo 'REDIS_URL=redis://localhost:6379/0' >> .env.local

# 5. 建表 + seed lookup 数据
alembic upgrade head
mysql -u intelops -pdev football_intel -e "SHOW TABLES;"   # 应看到 8 张表
mysql -u intelops -pdev football_intel -e "SELECT name FROM competitors;"   # 应看到 9 个竞品

# 6. 验证健康
python3 -m shared.db
# 输出 mysql.ok=true, redis.ok=true，所有表行数 0

# 7. 跑一次同步看数据流
python3 scripts/daily_sync.py
mysql -u intelops -pdev football_intel -e "
  SELECT 'reviews' tbl, COUNT(*) n FROM reviews UNION
  SELECT 'community_posts', COUNT(*) FROM community_posts UNION
  SELECT 'iap_items', COUNT(*) FROM iap_items UNION
  SELECT 'market_rank_snapshots', COUNT(*) FROM market_rank_snapshots UNION
  SELECT 'sync_log', COUNT(*) FROM sync_log;
"
```

### 日常使用

| 任务 | 命令 |
|---|---|
| 启动 DB | `docker compose up -d` |
| 停止 DB（保留数据） | `docker compose down` |
| 完全清空数据 | `docker compose down -v` |
| 看运行状态 | `docker compose ps` |
| 进 MySQL CLI | `mysql -u intelops -pdev football_intel` |
| 进 Redis CLI | `redis-cli` |

### 升级 schema

```bash
# 改 shared/models.py 后，自动生成 revision
alembic revision --autogenerate -m "add new column"
# 看 migrations/versions/xxxx.py 是否符合预期，没问题就 apply
alembic upgrade head
```

### GUI 工具推荐

| 工具 | 平台 | MySQL | Redis | 备注 |
|---|---|---|---|---|
| **TablePlus** | Mac | ✅ | ✅ | 免费版限 2 连接，够用 |
| Sequel Ace | Mac | ✅ | — | 完全免费 |
| DBeaver | 跨平台 | ✅ | ✅（社区版插件） | 免费 |
| RedisInsight | 跨平台 | — | ✅ | Redis 官方 |

连接信息（开发期）：
- **MySQL**: `localhost:3306` / user `intelops` / pwd `dev` / db `football_intel`
- **Redis**: `localhost:6379`

### 上线时迁云

把 `.env.local` 的 `MYSQL_DSN` 改成云数据库 endpoint 即可，代码无感：

```bash
# 阿里云 RDS
MYSQL_DSN=mysql+pymysql://user:pwd@xxx.mysql.rds.aliyuncs.com:3306/football_intel?charset=utf8mb4

# Supabase
MYSQL_DSN=mysql+pymysql://user:pwd@db.xxx.supabase.co:6543/football_intel?charset=utf8mb4
```

迁移建议：本地 `mysqldump` → 云 `mysql -h xxx <`，或者直接 `alembic upgrade head` 在云 DB 上重建空表。

### 双写降级行为

- **MYSQL_DSN 未配置** → 抓取脚本仅写 JSON（与 db 集成前一样），dao 函数 return 0
- **MYSQL_DSN 配好但 docker 未启动** → dao 函数捕获连接异常，log warning，return 0，主流程不挂
- **REDIS_URL 未配置** → sync_state / retry_queue 仍用 JSON 文件，dashboard 卡片显示"Redis 未配置"

---

## 跨机器迁移：`~/.intelops-secrets`

**问题**：`.env.local` 在仓库根目录、被 gitignore，每台机器都要手动维护。

**解决**：把所有 key 放到 `~/.intelops-secrets`（家目录文件，永远在仓库外）。
`shared/env_loader.load_all()` 会按这个顺序加载：

1. `<project_root>/.env.local`（项目专属，per-clone）
2. `~/.intelops-secrets`（用户级 fallback，跨项目跨机器）

两个文件同名变量以**先加载的为准**（即 `.env.local` 优先，`~/.intelops-secrets` 兜底）。已存在的 shell `export` 又比这俩都优先。

### 第一次设置（在你常用的那台 Mac）

```bash
# 1. 创建家目录配置文件
cat > ~/.intelops-secrets <<'EOF'
CLAUDE_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
X_BEARER_TOKEN=...
GOOGLE_API_KEY=...
GOOGLE_CSE_ID=...
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
FEISHU_KEYWORD=INTEL-OPS
EOF

# 2. 锁权限（仅自己可读）
chmod 600 ~/.intelops-secrets

# 3. 验证读得到
python3 -m shared.env_loader
# 输出应列出每个 key 的 <set>/<empty> 状态
```

之后这台 Mac 上**项目根的 `.env.local` 可以为空 / 不存在**，所有 key 都从家目录读。

### 迁移到新 Mac

**方案 1：iCloud Drive 同步（推荐）**

```bash
# 在原 Mac 上把家目录文件移到 iCloud Drive
mkdir -p ~/Library/Mobile\ Documents/com~apple~CloudDocs/intelops
mv ~/.intelops-secrets ~/Library/Mobile\ Documents/com~apple~CloudDocs/intelops/.intelops-secrets
ln -s ~/Library/Mobile\ Documents/com~apple~CloudDocs/intelops/.intelops-secrets ~/.intelops-secrets

# 在新 Mac 上（前提：iCloud Drive 已同步）
ln -s ~/Library/Mobile\ Documents/com~apple~CloudDocs/intelops/.intelops-secrets ~/.intelops-secrets
chmod 600 ~/Library/Mobile\ Documents/com~apple~CloudDocs/intelops/.intelops-secrets

# 验证
python3 -m shared.env_loader
```

改一处所有机器同步，永远不用重填。

**方案 2：手工复制**

```bash
# 原 Mac 上
scp ~/.intelops-secrets newmac.local:~/

# 新 Mac 上
chmod 600 ~/.intelops-secrets
```

**方案 3：dotfiles 仓库**

如果你已经维护一个**私有** dotfiles 仓库（注意：私有，不能是 public），把 `~/.intelops-secrets` 链接进去，git 同步即可。`football-intel-suite` 仓库本身是 public，**绝对不能**把这个文件提交进来。

### 安全要点

- ❌ 永远不要 `git add ~/.intelops-secrets` 到 public 仓库
- ❌ 永远不要把 webhook URL / API key 硬编码到代码里
- ✅ `chmod 600` 让别的用户读不到
- ✅ 飞书 webhook 一旦泄露 → 删旧机器人重建一个就好（5 秒钟的事）

---

## 常见操作

### 把某 task 切到更强模型

```jsonc
"tasks": {
  "review_3d": { "model": "sonnet_4_6", ... }   // ← 改这一行
}
```

### 全局升级模型版本（如 opus 4.6 → 4.7）

```jsonc
"models": {
  "opus_4_6": { "name": "claude-opus-4-7", ... }   // ← 改 name 一行
}
```

### 临时调温度（不改文件）

```bash
export AI_OVERRIDE__review_3d__temperature=0.7
export AI_OVERRIDE__review_3d__max_tokens=8192
export AI_OVERRIDE__weekly_review_report__model=sonnet_4_6
```

格式：`AI_OVERRIDE__<task_name>__<field>=<value>`

### 临时换 key（一次性）

浏览器顶部「API Key」输入框填入即可（仅当前会话生效，覆盖 .env.local）。

### 调试：看某 task 解析后的真实配置

```bash
python3 -m shared.ai_client review_3d --explain
```

会打印合并后的最终 cfg（含 endpoint URL / 模型名 / 超时 / fallback 等），可定位"为啥跑的不是我以为的那个模型"。

---

## 自动 Fallback

每个 model 都配了：

```jsonc
"fallback_endpoint": "anthropic_official",
"fallback_on_status": [502, 503, 504, 429]
```

中转 5xx 或限流时自动切官方端点，业务无感。需要 `ANTHROPIC_API_KEY` 已配置才生效。

---

## 业务代码怎么用

```python
from shared.ai_client import run_task

result = run_task("review_3d", context={
    "competitor": "SofaScore",
    "days": 3,
    "count": len(reviews),
    "samples": format_samples(reviews),
})
# result 已经是 dict（output_format=json）或 str（=text）
```

新增任务：在 `ai_tasks.json::tasks` 加一条 + （可选）在 `prompts/` 加 builder。**不用动 ai_client.py**。

---

## 文件位置速查

```
config/ai_tasks.json        ← 配置
shared/ai_client.py         ← 统一入口 run_task()
shared/env_loader.py        ← .env.local 加载
prompts/comment_prompts.py  ← 评论类 prompt builder
prompts/community_prompts.py ← 社媒
prompts/ads_prompts.py      ← 广告
.env.local                  ← key（gitignored）
.env.local.example          ← key 模板
```
