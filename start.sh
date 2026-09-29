#!/bin/bash
# start.sh · bid-master 一键启动入口（DEV-0058）
# 用法：./start.sh [start|stop|restart|status]（缺省 = start）
# 坑位规避：服务真实进程名是框架二进制（Python server.py），pkill -f 模式静默失配——
#          一律用 lsof -tiTCP:8080 按端口定位 PID。
set -u
cd "$(dirname "$0")"

PORT=8080
LOG=/tmp/bid-board.log
HEALTH="http://127.0.0.1:${PORT}/api/v1/health"

# Python 统一走项目 venv（crawl4ai/playwright 依赖在 venv）
if [ -x ".venv/bin/python3" ]; then
  PY=".venv/bin/python3"
else
  PY="python3"
  echo "⚠  未找到 .venv（crawl4ai 抓取引擎不可用）；如需安装：make install-capture"
fi

pid_on_port() { lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1; }

do_stop() {
  local pid
  pid=$(pid_on_port)
  if [ -z "$pid" ]; then
    echo "○ 端口 ${PORT} 无服务在跑"
    return 0
  fi
  local orig_pid="$pid"
  kill "$pid" 2>/dev/null
  for _ in $(seq 1 10); do
    pid=$(pid_on_port) || true
    [ -z "$pid" ] && break
    sleep 1
  done
  if [ -n "$(pid_on_port)" ]; then
    kill -9 "$(pid_on_port)" 2>/dev/null
    sleep 1
  fi
  if [ -z "$(pid_on_port)" ]; then
    echo "🛑 服务已停止（PID ${orig_pid}）"
  else
    echo "⛔ 端口 ${PORT} 仍被占用：" && lsof -i ":${PORT}" | tail -2
    return 1
  fi
}

do_start() {
  if [ -n "$(pid_on_port)" ]; then
    echo "⚠  端口 ${PORT} 已有服务（PID $(pid_on_port)），先停旧实例…"
    do_stop || return 1
  fi
  echo "🚀 启动 bid-master 统一服务（${PY} server.py）…"
  nohup "$PY" server.py > "$LOG" 2>&1 &
  local pid=$!
  # 健康检查重试（服务装配约需 1~3s，单次 sleep 2 曾偶发误报失败）
  local ok=""
  for _ in $(seq 1 15); do
    if curl -s --max-time 2 "$HEALTH" | grep -q '"ok": *true'; then ok=1; break; fi
    sleep 1
  done
  if [ -z "$ok" ]; then
    echo "❌ 启动失败（15s 内健康检查未过），日志尾部："
    tail -5 "$LOG"
    return 1
  fi
  echo "✅ 服务已就绪（PID $(pid_on_port)）"
  echo ""
  echo "  看板:      http://127.0.0.1:${PORT}/"
  echo "  API:       http://127.0.0.1:${PORT}/api/v1/bids"
  echo "  健康:      ${HEALTH}"
  echo "  日志:      $LOG"
  echo ""
  # 调度器状态（DEV-0081 起调度内置服务：随本服务起停，3h 一轮）
  local marker="$HOME/.bidmaster/.sched-migrated"
  if [ -f "$marker" ]; then
    echo "  调度器:    ✅ 服务内置 3h 一轮（capture→qualify→validate→复核→收割→一致性→digest）"
    echo "             状态/手动触发：GET|POST http://127.0.0.1:${PORT}/api/v1/scheduler[/run]"
  else
    echo "  调度器:    ⚠  迁移标记缺失（~/.bidmaster/.sched-migrated）——旧 crontab/launchd 若仍在将被放行"
  fi
  if crontab -l 2>/dev/null | grep -q "bid-master"; then
    echo "  ℹ  旧 crontab 条目仍在（已被迁移闸门中和为 no-op）；有空时手动清退：crontab -r"
  fi
  echo ""
  echo "  停止: $(basename "$0") stop"
}

do_status() {
  local pid
  pid=$(pid_on_port)
  if [ -z "$pid" ]; then
    echo "○ 服务未运行"
    return 1
  fi
  echo "✅ 运行中 PID $pid"
  curl -s --max-time 2 "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "（健康端点无响应）"
  echo "最近日志："
  tail -3 "$LOG"
}

case "${1:-start}" in
  start)   do_start ;;
  stop)    do_stop ;;
  restart) do_stop && do_start ;;
  status)  do_status ;;
  *) echo "用法：$(basename "$0") [start|stop|restart|status]"; exit 3 ;;
esac
