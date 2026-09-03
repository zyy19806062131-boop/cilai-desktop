#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "========================================================"
echo "  正在重新打包并更新桌面应用「词来.app」..."
echo "========================================================"

# 精确清理 8765 端口和词来主程序，不波及同名脚本或其它项目
lsof -ti tcp:8765 2>/dev/null | xargs -r kill 2>/dev/null || true
pkill -f "Desktop/词来.app/Contents/MacOS/词来" 2>/dev/null || true
sleep 1

node scripts/package-mac.js

echo ""
echo "========================================================"
echo "  ✓ 桌面上的「词来.app」已成功更新为最新版本！"
echo "  历史生词与学生档案存储在 ~/Library/Application Support/cilai/，更新完全保留。"
echo "========================================================"
sleep 2
