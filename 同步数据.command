#!/bin/bash
# INTEL-OPS 数据同步启动器 — 串行跑 daily_sync + weekly_sync
# 日志同时写 logs/sync_combined_TIMESTAMP.log 和终端
# 完成后从 sync_log.json 显示今日成功/失败统计
#
# 用法：双击此文件（macOS 在新 Terminal 窗口跑），或在终端 ./同步数据.command
# 总耗时：daily ~15-30min + weekly ~5-10min ≈ 25-40min

set -u
set -o pipefail

cd "$(dirname "$0")"
ROOT="$(pwd)"

# ─── 1. 检测是否有现成 sync 进程在跑 ───
EXISTING="$(pgrep -f 'scripts/(daily|weekly)_sync\.py' || true)"
if [ -n "$EXISTING" ]; then
  echo "⚠️  已有 sync 进程在跑（PID: $EXISTING）"
  echo "    要重跑请先 kill：kill $EXISTING"
  echo ""
  read -n 1 -s -r -p "按任意键关闭..."
  exit 1
fi

# ─── 2. 加载 .env.local ───
if [ -f ".env.local" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env.local
  set +a
else
  echo "❌ 缺少 .env.local"
  echo "   首次：cp .env.local.example .env.local，编辑填入 API key"
  echo ""
  read -n 1 -s -r -p "按任意键关闭..."
  exit 1
fi

# ─── 3. 日志路径 ───
mkdir -p logs
TS="$(date +%Y%m%d_%H%M%S)"
LOG="logs/sync_combined_$TS.log"

echo "════════════════════════════════════════"
echo "  INTEL-OPS 数据同步"
echo "════════════════════════════════════════"
echo "  开始: $(date '+%Y-%m-%d %H:%M:%S')"
echo "  预计: daily ~15-30min + weekly ~5-10min"
echo "  日志: $LOG"
echo "  仓库: $ROOT"
echo ""
echo "  Ctrl+C 中止；中止后已跑的源不会回滚。"
echo "════════════════════════════════════════"
echo ""

# ─── 4. 串行跑 daily 然后 weekly；tee 同时写日志 + 终端 ───
START=$(date +%s)
{
  python3 -u scripts/daily_sync.py \
    && echo "" \
    && echo "════════ DAILY 完成，开始 WEEKLY ════════" \
    && echo "" \
    && python3 -u scripts/weekly_sync.py
} 2>&1 | tee "$LOG"
EXIT_CODE=${PIPESTATUS[0]}
END=$(date +%s)
DUR=$((END - START))

echo ""
echo "════════════════════════════════════════"
if [ "$EXIT_CODE" -eq 0 ]; then
  echo "  ✅ 同步完成（耗时 $((DUR / 60))m $((DUR % 60))s）"
else
  echo "  ❌ 同步异常退出（exit=$EXIT_CODE，耗时 $((DUR / 60))m $((DUR % 60))s）"
fi
echo "════════════════════════════════════════"
echo ""

# ─── 5. 今日事件总结（从 sync_log.json） ───
TODAY=$(date +%Y-%m-%d)
python3 - "$TODAY" <<'PYEOF'
import json, sys
target = sys.argv[1]
try:
    events = json.load(open("data/sync_log.json"))
except Exception as e:
    print(f"  (无法读 sync_log.json: {e})")
    sys.exit(0)
todays = [e for e in events if e.get("started_at","").startswith(target)]
ok = sum(1 for e in todays if e.get("success"))
fail = sum(1 for e in todays if not e.get("success"))
print(f"  今日事件: {len(todays)}（成功 {ok} / 失败 {fail}）")
if fail:
    print("  失败项:")
    for e in todays:
        if not e.get("success"):
            print(f"    - {e.get('script',''):25s} err={e.get('error_kind')}")
PYEOF

echo ""
read -n 1 -s -r -p "按任意键关闭..."
echo ""
