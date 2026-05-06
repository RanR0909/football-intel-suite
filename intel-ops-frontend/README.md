# INTEL-OPS Frontend

INTEL-OPS · All Football 竞品情报系统 v2.0 · 前端

> 配套后端文档：[`../docs/BACKEND.md`](../docs/BACKEND.md)
> 配套数据源文档：[`../docs/DATA_SOURCES.md`](../docs/DATA_SOURCES.md)
> 设计 spec：[`../INTEL-OPS_前端实现文档_v2.md`](../INTEL-OPS_前端实现文档_v2.md)（如已合入仓库）

---

## 技术栈

| 类别 | 选型 |
|---|---|
| 框架 | React 18 + TypeScript 5 |
| 构建 | Vite 5 |
| 路由 | React Router v6 |
| 状态 | Zustand |
| API | TanStack Query v5 + axios |
| 样式 | Tailwind CSS 3 + shadcn/ui |
| 表格 | TanStack Table v8 |
| 图标 | lucide-react |
| 通知 | sonner |
| Mock | MSW（仅开发期可选） |

不引入：图表库、动画库、表单库、emoji。

---

## 启动

### 1. 安装依赖

```bash
cd intel-ops-frontend
pnpm install        # 或 npm install / yarn
```

### 2. 启动后端 API

```bash
# 在仓库根目录
python3 main_dashboard/dashboard_server.py
# → http://localhost:8899
```

### 3. 启动前端

```bash
pnpm dev
# → http://localhost:5173
```

Vite 已配置代理：`/api/*` → `http://localhost:8899/api/*`，前端代码用 `axios.get("/alerts")` 即可。

### 4. （可选）只跑前端不依赖后端

```bash
echo "VITE_USE_MOCK=1" > .env.local
pnpm dev
```

MSW 拦截 4 个核心端点，返回内置假数据用于 UI 调试。

---

## 目录结构

```
src/
├── pages/              # 14 个页面
│   ├── Overview.tsx        # 总览看点
│   ├── AlertCenter.tsx     # 预警中心
│   ├── data/
│   │   ├── Rankings.tsx    # 排名异动
│   │   ├── Revenue.tsx     # 收入下载
│   │   ├── IAP.tsx         # IAP 内购
│   │   └── Website.tsx     # 网站数据
│   ├── content/
│   │   ├── Releases.tsx    # 产品动态
│   │   ├── GPReviews.tsx   # GP 评论
│   │   ├── Social.tsx      # 社媒评论
│   │   ├── News.tsx        # 商业新闻
│   │   └── Ads.tsx         # 广告投放
│   └── system/
│       ├── Candidates.tsx  # 候选发现
│       ├── FailedJobs.tsx  # AI 失败队列
│       └── SyncLog.tsx     # 同步日志
├── components/
│   ├── ui/             # shadcn/ui (initialize 后自动生成)
│   ├── layout/
│   │   ├── PageLayout.tsx
│   │   ├── Sidebar.tsx
│   │   └── SyncStatusBar.tsx
│   └── shared/
│       ├── PageHeader.tsx
│       ├── PagePlaceholder.tsx
│       ├── DigestCard.tsx
│       ├── EmptyState.tsx
│       └── Skeleton.tsx
├── hooks/
│   ├── useUrlFilters.ts        # URL 同步筛选
│   └── api/                    # TanStack Query hooks
│       ├── useDashboardData.ts
│       ├── useAlerts.ts
│       ├── useCandidates.ts
│       └── useReviews.ts
├── stores/
│   ├── globalStore.ts          # 侧边栏 / 主题
│   └── filterStore.ts          # 跨页筛选记忆
├── lib/
│   ├── api.ts                  # axios 实例
│   ├── baseline.ts             # vs baseline 计算
│   └── utils.ts                # cn() / 格式化
├── types/
│   ├── api.ts                  # 后端响应类型
│   └── domain.ts               # 业务领域常量
├── mocks/                      # MSW 拦截器
│   ├── browser.ts
│   └── handlers.ts
├── App.tsx
├── router.tsx
├── main.tsx
└── index.css
```

---

## 开发约定

### 1. 设计风格（重要）

| 做 | 不做 |
|---|---|
| 表格 + 数字 + 短文本 | 趋势图 / 折线图 |
| 黑白灰为主 + AF 绿主色 | 多色装饰 / 渐变 |
| 0.5px 极淡边框 / 紧凑间距 | 大圆角 / 大阴影 / 玻璃拟态 |
| 字号 11-14px 为主 | 大标题字号叙事 |
| 数字直接看 | "这是什么"小字解释 |
| lucide-react 图标 | **emoji（任何场合都不用）** |
| 表格 hover 微亮 | 入场动画 / 数字增长动画 |

### 2. 颜色

```ts
// AF 绿（主）
brand-500: #00D616

// 语义
semantic-success: #1D9E75   // 我方领先（vs baseline）
semantic-warning: #EF9F27   // 中优预警
semantic-danger:  #E24B4A   // 高优预警 / 我方落后
semantic-info:    #185FA5   // AF baseline 行高亮
```

### 3. URL 同步筛选

每个子页用 `useUrlFilters` 把筛选状态写到 URL，方便复制链接 / 浏览器前进后退：

```tsx
const { value, setValue } = useUrlFilters({ source: "appmagic", region: "" })
<Select value={value("source")} onValueChange={(v) => setValue("source", v)} />
```

### 4. AppScope（仅竞品 / 仅 AF / 全部）

内容类页面顶部加 chip 三选，**默认仅竞品**。状态走 `filterStore.appScope` 跨页记忆。

---

## API 端点

| 端点 | 用途 |
|---|---|
| `GET /api/data/dashboard_data` | 完整聚合数据 |
| `GET /api/status` | 各源状态 / retry / failed |
| `GET /api/alerts` | 预警事件（filter: status / type / severity / since） |
| `POST /api/alerts/:id/ack` | 标记预警已读 |
| `GET /api/reviews` | 评论（含翻译 + 实体 join） |
| `GET /api/iap` | IAP 商品 |
| `GET /api/rank` | 排名快照 |
| `GET /api/news` | 商业新闻 |
| `GET /api/ads` | Meta 广告创意 |
| `GET /api/website` | Similarweb 网站数据 |
| `GET /api/candidates` | AI 候选 app（自动排除已 in competitors） |
| `GET /api/failed-ai-jobs` | AI 失败队列 |
| `POST /api/failed-ai-jobs/:id/retry` | 重置失败任务 |
| `GET /api/sync-log` | 抓取作业日志 |

完整字段定义见 `src/types/api.ts`。

---

## Stage 1 交付状态（当前 commit）

✅ 已完成：

1. Vite + TS + Tailwind + shadcn/ui 配置完整
2. `tailwind.config.ts` + `index.css` 按设计 spec
3. Geist + JetBrains Mono 字体加载
4. 14 个路由 + 14 个页面占位组件
5. `<Sidebar />` 三层分组导航 + URL 同步 + badge
6. `<SyncStatusBar />` 13 数据源状态横向铺开
7. axios + TanStack Query 配好 + interceptor 错误 toast
8. `EmptyState` / `Skeleton` / `DigestCard` / `PageHeader` 占位组件
9. MSW mock 4 个核心端点（dashboard / status / alerts / candidates）
10. 完整 TypeScript types（13 个 API 响应 + 业务领域常量）

⏳ 待 Stage 2/3：

- shadcn/ui 子组件 init（按需 `pnpm dlx shadcn-ui@latest add ...`）
- 总览页 9 个 DigestCard 真实内容
- 预警中心完整功能
- 11 个子页填充（按 P0 → P3 顺序）

---

## 常用命令

```bash
pnpm dev              # 开发服务器
pnpm build            # 生产构建
pnpm preview          # 本地预览构建产物
pnpm type-check       # TS 类型检查
pnpm lint             # ESLint
```

---

## 联调清单

后端开发需提供：

1. **API base URL**：dev `http://localhost:8899`，prod 域名待定
2. **CORS**：dashboard_server.py 默认允许 `localhost:5173` / `:4173`
3. **OpenAPI**：可选 — 用 `openapi-typescript` 生成更精确的类型
4. **WebSocket / SSE**：v1 暂用 30s 轮询（已实现），后续按需接入实时推送
