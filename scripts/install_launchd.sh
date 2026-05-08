#!/bin/bash
# 安装 INTEL-OPS 自动同步到 macOS launchd
#
# 装三个 agent：
#   com.intelops.daily   — 每天 02:00 跑 daily_sync.py
#   com.intelops.weekly  — 每周日 03:00 跑 weekly_sync.py
#   com.intelops.retry   — 每小时跑一次 daily_sync.py --retry-only
#
# launchd plist 模板里用 __PROJECT_ROOT__ 占位符，安装时 sed 替换成当前仓库路径。
# 这样换电脑 / 换用户名 / 换目录都不用手改 plist。
#
# 用法：
#   bash scripts/install_launchd.sh           # 装
#   bash scripts/uninstall_launchd.sh         # 卸

set -e

cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"
LAUNCHD_DIR="${HOME}/Library/LaunchAgents"

mkdir -p "${LAUNCHD_DIR}"

for label in com.intelops.daily com.intelops.weekly com.intelops.retry; do
    src="${PROJECT_ROOT}/launchd/${label}.plist"
    dst="${LAUNCHD_DIR}/${label}.plist"
    if [ ! -f "${src}" ]; then
        echo "❌ 找不到 ${src}"
        exit 1
    fi
    # 已存在先 unload，避免新旧 plist 同名冲突
    if launchctl list | grep -q "${label}"; then
        launchctl unload "${dst}" 2>/dev/null || true
    fi
    # 用 sed 把 __PROJECT_ROOT__ 替换成实际路径，再写到 LaunchAgents
    # 注意：路径里如果有 / 字符（必然有），用 | 当 sed 分隔符避免转义地狱
    sed "s|__PROJECT_ROOT__|${PROJECT_ROOT}|g" "${src}" > "${dst}"
    launchctl load "${dst}"
    echo "✅ 装好 ${label}  →  cd ${PROJECT_ROOT}"
done

echo ""
echo "查看状态：launchctl list | grep intelops"
echo "立刻触发一次 daily：launchctl start com.intelops.daily"
echo "立刻触发一次 retry：launchctl start com.intelops.retry"
echo "查看日志：tail -f /tmp/intelops-{daily,weekly,retry}.log"
echo "卸载：bash scripts/uninstall_launchd.sh"
echo ""
echo "调度：daily 02:00 / weekly 周日 03:00 / retry 每小时（只清队列）"
