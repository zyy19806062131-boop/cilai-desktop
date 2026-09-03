#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "========================================================"
echo "  正在启动 Preply 课堂生词速查与课后闪卡助手..."
echo "========================================================"

# 后台启动 Python 伴侣服务 (提供 AI 智能例句与全量检索)
python3 server.py &
SERVER_PID=$!

sleep 1

# 打开默认浏览器
open "http://127.0.0.1:8765"

echo ""
echo "助手已在浏览器中打开！"
echo "按 Ctrl+C 即可退出服务。"
echo "========================================================"

# 捕获退出信号，清理后台服务
trap "kill $SERVER_PID 2>/dev/null; exit" INT TERM EXIT

wait $SERVER_PID
