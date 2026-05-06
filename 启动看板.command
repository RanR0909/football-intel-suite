#!/bin/bash
# INTEL-OPS 看板启动器（v2 — 同时启动 dashboard_server :8899 + vite :5173）
# 密钥从 .env.local 加载（gitignored）；首次：cp .env.local.example .env.local 并填入

set -e
set -u
set -o pipefail

cd "$(dirname "$0")"
ROOT="$(pwd)"
FRONTEND_DIR="$ROOT/intel-ops-frontend"

# ─── 1. 加载 .env.local ───
if [ -f ".env.local" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env.local
  set +a
else
  echo "❌ 缺少 .env.local"
  echo "首次使用："
  echo "  cp .env.local.example .env.local"
  echo "  然后用编辑器填入真实 API key"
  exit 1
fi

# ─── 2. 校验关键 key ───
if [ -z "${CLAUDE_API_KEY:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "❌ 至少需要 CLAUDE_API_KEY（中转）或 ANTHROPIC_API_KEY（官方）之一"
  echo "   编辑 .env.local 填入"
  exit 1
fi

# ─── 3. 端口清理函数 ───
kill_port() {
  local port=$1
  local pids
  pids="$(lsof -ti:"$port" 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    echo "  释放 :$port (PID $pids)"
    echo "$pids" | xargs kill -TERM 2>/dev/null || true
    for _ in 1 2 3; do
      sleep 1
      [ -z "$(lsof -ti:"$port" 2>/dev/null || true)" ] && return 0
    done
    pids="$(lsof -ti:"$port" 2>/dev/null || true)"
    [ -n "$pids" ] && echo "$pids" | xargs kill -KILL 2>/dev/null || true
  fi
}

echo "── 释放旧端口 ──"
kill_port 8899
kill_port 5173

# ─── 4. 启动 backend dashboard_server :8899（脱离 session）───
echo "── 启动 backend (:8899) ──"
nohup python3 -u main_dashboard/dashboard_server.py 8899 \
  > /tmp/intelops-backend.log \
  2> /tmp/intelops-backend.err \
  < /dev/null &
disown
BACKEND_PID=$!

for _ in 1 2 3 4 5 6 7 8; do
  if curl -sf -o /dev/null --max-time 1 "http://127.0.0.1:8899/api/status"; then
    echo "  ✓ backend ready (PID $BACKEND_PID)"
    break
  fi
  sleep 1
done

if ! curl -sf -o /dev/null --max-time 1 "http://127.0.0.1:8899/api/status"; then
  echo "❌ backend 起不来，看 /tmp/intelops-backend.err"
  tail -20 /tmp/intelops-backend.err
  exit 1
fi

# ─── 5. 启动 vite 前端 :5173 ───
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo "❌ $FRONTEND_DIR/node_modules 不存在"
  echo "   先跑：cd intel-ops-frontend && npm install"
  exit 1
fi

echo "── 启动 vite (:5173) ──"
cd "$FRONTEND_DIR"
nohup node_modules/.bin/vite \
  > /tmp/intelops-vite.log \
  2> /tmp/intelops-vite.err \
  < /dev/null &
disown
VITE_PID=$!
cd "$ROOT"

for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sf -o /dev/null --max-time 1 "http://127.0.0.1:5173/"; then
    echo "  ✓ vite ready (PID $VITE_PID)"
    break
  fi
  sleep 1
done

if ! curl -sf -o /dev/null --max-time 1 "http://127.0.0.1:5173/"; then
  echo "❌ vite 起不来，看 /tmp/intelops-vite.err"
  tail -20 /tmp/intelops-vite.err
  exit 1
fi

# ─── 6. 打开浏览器到 v2 前端 ───
open http://127.0.0.1:5173/overview

echo ""
echo "════════════════════════════════════════"
echo "  ✅ INTEL-OPS 已启动"
echo "════════════════════════════════════════"
echo "  v2 前端:    http://127.0.0.1:5173/   (PID $VITE_PID)"
echo "  v2 后端 API: http://127.0.0.1:8899/  (PID $BACKEND_PID)"
echo ""
echo "  日志:"
echo "    backend out: /tmp/intelops-backend.log"
echo "    backend err: /tmp/intelops-backend.err"
echo "    vite out:    /tmp/intelops-vite.log"
echo "    vite err:    /tmp/intelops-vite.err"
echo ""
echo "  Key 状态:"
echo "    CLAUDE_API_KEY:    $([ -n "${CLAUDE_API_KEY:-}" ] && echo "已配置" || echo "未配置")"
echo "    ANTHROPIC_API_KEY: $([ -n "${ANTHROPIC_API_KEY:-}" ] && echo "已配置" || echo "未配置")"
echo "    X_BEARER_TOKEN:    $([ -n "${X_BEARER_TOKEN:-}" ] && echo "已配置" || echo "未配置（X 抓取会跳过）")"
echo "    MYSQL_DSN:         $([ -n "${MYSQL_DSN:-}" ] && echo "已配置" || echo "未配置（dao 降级 JSON-only）")"
echo "    REDIS_URL:         $([ -n "${REDIS_URL:-}" ] && echo "已配置" || echo "未配置")"
echo ""
echo "  停止：关闭此终端窗口；或："
echo "    lsof -ti:8899 | xargs kill"
echo "    lsof -ti:5173 | xargs kill"
echo ""

# 让脚本保持前台，关闭终端窗口能直接停服务
trap "echo '收到 Ctrl+C，停止服务...'; kill_port 5173; kill_port 8899; exit 0" INT TERM
echo "按 Ctrl+C 停止两个服务"
# 监控进程是否还活，任一死了就退出脚本
while true; do
  sleep 5
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "❌ backend 进程已退出，看 /tmp/intelops-backend.err"
    tail -20 /tmp/intelops-backend.err
    kill_port 5173
    exit 1
  fi
  if ! kill -0 "$VITE_PID" 2>/dev/null; then
    echo "❌ vite 进程已退出，看 /tmp/intelops-vite.err"
    tail -20 /tmp/intelops-vite.err
    kill_port 8899
    exit 1
  fi
done
