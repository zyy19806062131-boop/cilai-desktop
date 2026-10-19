#!/bin/bash
# 2026-10-19（小克）：把「语法点速查」同步进词来 app。
# 真源在工作区 汉语教学/lessons/_通用课/语法速查/（语法库、教法、生成预览页.py）。
# grammar/grammar.html 是生成产物，不要手改——改真源，再跑本脚本。
# 打包桌面 app 前（一键更新桌面版.command）必须先跑一遍，否则 app 里是旧版。
set -e
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../汉语教学/lessons/_通用课/语法速查" && pwd)"
DST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/grammar"
cd "$SRC"
/usr/bin/python3 生成预览页.py > /dev/null   # 自带四道闸，不过会 exit 非 0，set -e 停在这
mkdir -p "$DST"
cp "$SRC/预览_2026-10-17.html" "$DST/grammar.html"
echo "已同步：$DST/grammar.html"
