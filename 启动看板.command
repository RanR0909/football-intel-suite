#!/bin/bash
# INTEL-OPS v2.0 看板启动器
# 启动顺序：
#   ① 后端 API server (python · :8000)
#   ② 前端 dev server (vite · :5173)
#   ③ 浏览器打开 http://localhost:5173
# Ctrl+C 同时关掉两个进程

set -e

cd "$(dirname "$0")"
ROOT="$(pwd)"
FRONT="$ROOT/intel-ops-frontend"

# ─── 1. 加载 .env.local ────────────────────────────────────────
if [ -f ".env.local" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env.local
  set +a
else
  echo "❌ 缺少 .env.local"
  echo ""
  echo "首次使用，请先："
  echo "  cp .env.local.example .env.local"
  echo "  然后用编辑器填入 CLAUDE_API_KEY 等"
  echo ""
  exit 1
fi

# ─── 2. 校验关键 key ───────────────────────────────────────────
if [ -z "$CLAUDE_API_KEY" ] && [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "❌ 至少需要 CLAUDE_API_KEY（中转）或 ANTHROPIC_API_KEY（官方）之一"
  echo "   编辑 .env.local 填入"
  exit 1
fi

# ─── 3. 校验前端项目存在 ───────────────────────────────────────
if [ ! -d "$FRONT" ]; then
  echo "❌ 找不到前端项目 $FRONT"
  echo "   仓库可能不完整，请重新 clone / pull"
  exit 1
fi

# ─── 4. 杀旧进程（API :8000，Vite :5173） ──────────────────────
lsof -ti:8000 2>/dev/null | xargs kill -9 2>/dev/null || true
lsof -ti:5173 2>/dev/null | xargs kill -9 2>/dev/null || true
# 兼容旧版本端口（万一还有残留）
lsof -ti:8899 2>/dev/null | xargs kill -9 2>/dev/null || true

# ─── 5. 生成最新 dashboard_data.json ───────────────────────────
echo "▶ 生成 dashboard_data.json …"
python3 main_dashboard/generate_dashboard.py >/dev/null 2>&1 || \
  echo "  ⚠️  generate_dashboard 跑挂了；后端 API 仍可启动（前端会显示 503）"

# ─── 6. 启动后端 API（:8000） ──────────────────────────────────
mkdir -p /tmp/intel-ops
LOG_API="/tmp/intel-ops/api.log"
LOG_WEB="/tmp/intel-ops/web.log"

echo "▶ 启动后端 API …  日志: $LOG_API"
python3 main_dashboard/dashboard_server.py 8000 > "$LOG_API" 2>&1 &
PID_API=$!

# ─── 7. 启动前端 dev server（:5173） ──────────────────────────
cd "$FRONT"

# 选 package manager（优先 pnpm，否则 npm）
if command -v pnpm >/dev/null 2>&1; then
  PM="pnpm"
elif command -v npm >/dev/null 2>&1; then
  PM="npm"
else
  echo "❌ 未找到 pnpm / npm — 请先装 Node.js (https://nodejs.org)"
  kill $PID_API 2>/dev/null || true
  exit 1
fi

# 首次启动 / 依赖缺失 → 自动 install
if [ ! -d "node_modules" ]; then
  echo "▶ 首次运行，安装前端依赖（$PM install，可能需要 1-3 分钟）…"
  $PM install
fi

echo "▶ 启动前端 dev server …  日志: $LOG_WEB"
$PM run dev > "$LOG_WEB" 2>&1 &
PID_WEB=$!

cd "$ROOT"

# ─── 8. 等就绪 + 打开浏览器 ───────────────────────────────────
echo "▶ 等待服务器就绪 …"
for i in $(seq 1 20); do
  if curl -fs http://localhost:8000/api/health >/dev/null 2>&1 && \
     curl -fs http://localhost:5173 >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

open http://localhost:5173

# ─── 9. 状态打印 ──────────────────────────────────────────────
echo ""
echo "═════════════════════════════════════════════════════════════"
echo "✅ INTEL-OPS v2.0 已启动"
echo "═════════════════════════════════════════════════════════════"
echo "  后端 API   : http://localhost:8000   (PID $PID_API)"
echo "  前端 看板  : http://localhost:5173   (PID $PID_WEB)"
echo ""
echo "  CLAUDE_API_KEY     : $([ -n "$CLAUDE_API_KEY" ] && echo "✓ 已配" || echo "✗ 未配")"
echo "  ANTHROPIC_API_KEY  : $([ -n "$ANTHROPIC_API_KEY" ] && echo "✓ 已配" || echo "✗ 未配 (fallback)")"
echo "  UTOOLS_AUTH_TOKEN  : $([ -n "$UTOOLS_AUTH_TOKEN" ] && echo "✓ 已配 (Twitter via fapi.uk)" || echo "✗ 未配 (Twitter 跳过)")"
echo "  MYSQL_DSN          : $([ -n "$MYSQL_DSN" ] && echo "✓ 已配" || echo "✗ 未配 (退化为 JSON-only)")"
echo "  REDIS_URL          : $([ -n "$REDIS_URL" ] && echo "✓ 已配" || echo "✗ 未配 (sync_state 退化)")"
echo "  FEISHU_WEBHOOK_URL : $([ -n "$FEISHU_WEBHOOK_URL" ] && echo "✓ 已配" || echo "✗ 未配 (无飞书通知)")"
echo ""
echo "  实时日志："
echo "    后端: tail -f $LOG_API"
echo "    前端: tail -f $LOG_WEB"
echo ""
echo "  按 Ctrl+C 同时关闭两个服务"
echo "═════════════════════════════════════════════════════════════"
echo ""

# ─── 10. 优雅退出 ─────────────────────────────────────────────
cleanup() {
  echo ""
  echo "▶ 收到退出信号，正在停止 …"
  kill $PID_API 2>/dev/null || true
  kill $PID_WEB 2>/dev/null || true
  wait $PID_API 2>/dev/null || true
  wait $PID_WEB 2>/dev/null || true
  echo "  已停止"
  exit 0
}
trap cleanup INT TERM

# 任一进程挂掉 → 提示并退出
while kill -0 $PID_API 2>/dev/null && kill -0 $PID_WEB 2>/dev/null; do
  sleep 1
done

echo ""
if ! kill -0 $PID_API 2>/dev/null; then
  echo "❌ 后端 API 已退出 — 见 $LOG_API"
fi
if ! kill -0 $PID_WEB 2>/dev/null; then
  echo "❌ 前端 dev server 已退出 — 见 $LOG_WEB"
fi
cleanup
