#!/bin/bash
# toggle.command · bid-master 一键启停（双击即用 · DEV-0067）
# 行为：服务在跑 → 停止；未跑 → 启动。窗口停留显示结果，按任意键关闭。
# 桌面入口 ~/Desktop/bid-master启停.command 委托本文件。
cd "$(dirname "$0")"
PORT=8080

pid=$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1)
echo "════════════════════════════════════════"
echo "  bid-master 一键启停 · $(date '+%H:%M:%S')"
echo "════════════════════════════════════════"

if [ -n "$pid" ]; then
  echo "检测到服务运行中（PID ${pid}）→ 停止"
  bash ./start.sh stop
else
  echo "服务未运行 → 启动"
  bash ./start.sh start
  if curl -s --max-time 2 "http://127.0.0.1:${PORT}/api/v1/health" | grep -q '"ok"'; then
    echo ""
    echo "  看板: http://127.0.0.1:${PORT}/  （已在浏览器打开则刷新即可）"
  fi
fi

echo ""
echo "════════════════ 按任意键关闭本窗口 ════════════════"
if [ -t 0 ]; then
  read -n 1 -s -r
fi
