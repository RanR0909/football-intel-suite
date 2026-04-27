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
```

首次：`cp .env.local.example .env.local` 然后编辑。

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
