#!/bin/bash
cd "$(dirname "$0")"

# 设置 API Key（从前端默认值提取）
export CLAUDE_API_KEY="sk-REDACTED-OLD-FLASHAPI"

# 杀掉旧进程
lsof -ti:8899 | xargs kill -9 2>/dev/null

# 生成最新看板
python3 main_dashboard/generate_dashboard.py

# 启动服务器（后台）
python3 main_dashboard/dashboard_server.py &
SERVER_PID=$!

# 等待服务器就绪
sleep 1

# 打开浏览器
open http://localhost:8899

echo "服务器已启动 (PID: $SERVER_PID)，按 Ctrl+C 停止"
wait $SERVER_PID
