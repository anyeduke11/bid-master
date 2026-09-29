#!/usr/bin/env bash
# cron_baw.sh · BAW 周期任务手动入口（DEV-0081 起调度已迁服务内置——本脚本保留为 CLI 手动触发用）
# 用法：cron_baw.sh <consistency|digest|capture|scout-validate|ingest|lead-status-check>
# 锁：mkdir 单实例按任务独立（.cron_baw.<task>.running）——capture 慢不再饿死 digest；
#     全部输出留痕 ~/.bidmaster/log/cron-<任务>.log
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
TASK="${1:-}"
LOG_DIR="$HOME/.bidmaster/log"
# DEV-0081 迁移闸门：调度已迁服务内置（3h 一轮）。此标记存在期间，本脚本对任何调用方
# （残留 crontab / launchd）直接跳过——crontab 二进制写操作在本机挂 TCC 授权弹窗，
# 条目清退留待 owner 手动（crontab -r），标记先一步把旧条目变成无害 no-op。
# 手动执行底层任务：删本标记，或直接跑 rules|scripts 下对应脚本。
if [ -f "$HOME/.bidmaster/.sched-migrated" ]; then
  echo "$(date '+%F %T') ⏭ 调度已迁服务内置（DEV-0081），cron_baw.sh 入口停用：$TASK"
  exit 0
fi
mkdir -p "$LOG_DIR" "$HOME/.bidmaster/leads/raw"
# Python 统一走项目 venv（crawl4ai/playwright 依赖在 venv；无 venv 回退系统 python3）
if [ -x "$REPO/.venv/bin/python3" ]; then
  PYTHON="$REPO/.venv/bin/python3"
else
  PYTHON="python3"
fi
# 单实例锁（按任务分锁；陈旧锁 >2h 自动清，防崩溃残留卡死）
LOCKDIR="$LOG_DIR/.cron_baw.$TASK.running"
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  if [ -d "$LOCKDIR" ] && [ -n "$(find "$LOCKDIR" -maxdepth 0 -mmin +120 2>/dev/null)" ]; then
    echo "$(date '+%F %T') ⚠ 陈旧锁（>2h）已清，继续执行"
    rmdir "$LOCKDIR" 2>/dev/null || { echo "$(date '+%F %T') ⛔ 清理失败，跳过本次"; exit 0; }
    mkdir "$LOCKDIR" 2>/dev/null || { echo "$(date '+%F %T') ⛔ 抢锁失败，跳过本次"; exit 0; }
  else
    echo "$(date '+%F %T') ⛔ 上一实例未结束，跳过本次"
    exit 0
  fi
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null' EXIT

case "$TASK" in
  consistency)
    echo "$(date '+%F %T') consistency：跨标冲突/证照预警 → alerts.json"
    "$PYTHON" "$REPO/rules/consistency.py" >> "$LOG_DIR/cron-consistency.log" 2>&1 || true
    ;;
  digest)
    echo "$(date '+%F %T') digest：digest_stats.py 保底统计"
    "$PYTHON" "$REPO/scripts/digest_stats.py" >> "$LOG_DIR/cron-digest.log" 2>&1 || true
    ;;
  capture)
    echo "$(date '+%F %T') capture：lead_capture.sh（crawl4ai 引擎）→ ~/.bidmaster/leads/raw/"
    bash "$REPO/scripts/lead_capture.sh" >> "$LOG_DIR/cron-capture.log" 2>&1 || true
    ;;
  scout-validate)
    echo "$(date '+%F %T') scout-validate：抓取后跑 scout（工单/人工），再机检转正"
    "$PYTHON" "$REPO/rules/validate_leads.py" >> "$LOG_DIR/cron-validate.log" 2>&1 || true
    ;;
  ingest)
    echo "$(date '+%F %T') ingest：外部收割（实收；只收 tender/lead-table——owner 2026-09-26 批准，DEV-0081）"
    "$PYTHON" "$REPO/rules/ingest.py" --all --types tender,lead-table >> "$LOG_DIR/cron-ingest.log" 2>&1 || true
    ;;
  lead-status-check)
    # 11:00 / 17:00 节拍（owner 2026-09-13 定）：拉所有带原文链接的 lead 详情页，
    # 经 lead_status_normalize 归 5 态，侦测状态转移 → 写 leads.status_* + events。
    echo "$(date '+%F %T') lead-status-check：拉原文 → 5态 → 侦测转移"
    "$PYTHON" "$REPO/rules/lead_status_check.py" --limit 50 >> "$LOG_DIR/cron-lead-status.log" 2>&1 || true
    ;;
  *)
    echo "未知任务：${TASK}（可选：consistency|digest|capture|scout-validate|ingest|lead-status-check）"
    exit 3
    ;;
esac
