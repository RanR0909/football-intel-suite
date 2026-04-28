#!/bin/bash
# 卸载 INTEL-OPS 自动同步 launchd agents
set -e

LAUNCHD_DIR="${HOME}/Library/LaunchAgents"

for label in com.intelops.daily com.intelops.weekly; do
    plist="${LAUNCHD_DIR}/${label}.plist"
    if [ -f "${plist}" ]; then
        launchctl unload "${plist}" 2>/dev/null || true
        rm -f "${plist}"
        echo "✅ 卸载 ${label}"
    else
        echo "（${label} 未安装）"
    fi
done
