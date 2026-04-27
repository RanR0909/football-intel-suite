#!/bin/bash
# INTEL-OPS 看板启动器
# 密钥从 .env.local 加载（gitignored）；首次使用：cp .env.local.example .env.local 并填入

cd "$(dirname "$0")"

# ─── 1. 加载 .env.local（含 CLAUDE_API_KEY / ANTHROPIC_API_KEY / X_BEARER_TOKEN） ───
if [ -f ".env.local" ]; then
  set -a              # 自动 export 后续变量
  # shellcheck disable=SC1091
  source .env.local
  set +a
else
  echo "❌ 缺少 .env.local"
  echo ""
  echo "首次使用，请先："
  echo "  cp .env.local.example .env.local"
  echo "  然后用编辑器填入真实 API key"
  echo ""
  exit 1
fi

# ─── 2. 校验关键 key ───
if [ -z "$CLAUDE_API_KEY" ] && [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "❌ 至少需要 CLAUDE_API_KEY（中转）或 ANTHROPIC_API_KEY（官方）之一"
  echo "   编辑 .env.local 填入"
  exit 1
fi

# ─── 3. 杀掉旧服务进程 ───
lsof -ti:8899 | xargs kill -9 2>/dev/null

# ─── 4. 生成最新看板 ───
python3 main_dashboard/generate_dashboard.py

# ─── 5. 启动后端 API 服务器（后台） ───
python3 main_dashboard/dashboard_server.py &
SERVER_PID=$!

# ─── 6. 等待就绪 + 打开浏览器 ───
sleep 1
open http://localhost:8899

echo ""
echo "✅ 服务器已启动 (PID: $SERVER_PID)"
echo "   - 中转 key:  $([ -n "$CLAUDE_API_KEY" ] && echo "已配置" || echo "未配置")"
echo "   - 官方 key:  $([ -n "$ANTHROPIC_API_KEY" ] && echo "已配置" || echo "未配置")"
echo "   - X token:   $([ -n "$X_BEARER_TOKEN" ] && echo "已配置" || echo "未配置（X 社媒抓取会跳过）")"
echo ""
echo "   按 Ctrl+C 停止"

wait $SERVER_PID
