#!/bin/bash
# 安装 INTEL-OPS 自动同步到 macOS launchd
#
# 装两个 agent：
#   com.intelops.daily   — 每天 02:00 跑 daily_sync.py
#   com.intelops.weekly  — 每周日 03:00 跑 weekly_sync.py
#
# 用法：
#   bash scripts/install_launchd.sh           # 装
#   bash scripts/uninstall_launchd.sh         # 卸

set -e

cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"
LAUNCHD_DIR="${HOME}/Library/LaunchAgents"

mkdir -p "${LAUNCHD_DIR}"

for label in com.intelops.daily com.intelops.weekly; do
    src="${PROJECT_ROOT}/launchd/${label}.plist"
    dst="${LAUNCHD_DIR}/${label}.plist"
    if [ ! -f "${src}" ]; then
        echo "❌ 找不到 ${src}"
        exit 1
    fi
    # 如果已存在先 unload
    if launchctl list | grep -q "${label}"; then
        launchctl unload "${dst}" 2>/dev/null || true
    fi
    cp "${src}" "${dst}"
    launchctl load "${dst}"
    echo "✅ 装好 ${label}"
done

echo ""
echo "查看状态：launchctl list | grep intelops"
echo "立刻触发一次 daily：launchctl start com.intelops.daily"
echo "查看日志：tail -f /tmp/intelops-daily.log /tmp/intelops-daily.err"
echo "卸载：bash scripts/uninstall_launchd.sh"
