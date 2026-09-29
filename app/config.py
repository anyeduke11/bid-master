#!/usr/bin/env python3
"""app/config.py · 配置中心（DEV-0042 单系统整合）

所有路径/开关集中于此，支持环境变量覆盖（可测试性；默认与原 v0.3.2 行为对齐，
但数据面统一收敛到 BIDMASTER_HOME——~/.bidboard 退役）。
"""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PUBLIC_DIR = REPO / "public"
SCRIPTS_DIR = REPO / "scripts"

# 数据根：与 rules/store.py、rules/set_stage.py 共用同一变量（密封测试 / 生产同一语义）
BIDMASTER_HOME = Path(os.environ.get("BIDMASTER_HOME") or (Path.home() / ".bidmaster"))

# 服务自有库（观察层）：leads / events / 命令审计 / 活动日志 / 抓取批次
APP_DB_PATH = BIDMASTER_HOME / "app.db"

# 目录
AGENT_QUEUE_DIR = BIDMASTER_HOME / "agent_queue"
DIGEST_DIR = BIDMASTER_HOME / "digests"
DIGEST_TMP = DIGEST_DIR / ".tmp"
LOG_JSONL = BIDMASTER_HOME / "log.jsonl"
ALERTS_JSON = BIDMASTER_HOME / "alerts.json"          # 一致性告警（consistency.py 产出）
LARK_CONFIG = BIDMASTER_HOME / "lark_config.json"

# lead 数据面（watcher 监听 + 抓取落盘，唯一入口；~/.bidboard/leads.jsonl 退役）
LEADS_DIR = BIDMASTER_HOME / "leads"
LEAD_WATCH_FILES = (
    LEADS_DIR / "raw" / "leads.jsonl",                # lead_capture.py 产出
    LEADS_DIR / "qualify.jsonl",                      # qualify_score.py 产出
)

# 服务开关
PORT = int(os.environ.get("BIDBOARD_PORT", "8080"))
BIDBOARD_EMPTY = os.environ.get("BIDBOARD_EMPTY") in ("1", "true", "yes")
FRESH_DAYS_DEFAULT = "90" if os.environ.get("BID_BOARD_DEMO_MODE", "0") == "1" else "45"
LEAD_FRESH_DAYS = int(os.environ.get("BID_BOARD_FRESH_DAYS", FRESH_DAYS_DEFAULT))
SKIP_REACH = os.environ.get("BID_BOARD_SKIP_REACH", "0") == "1"

# 契约/知识（智能体接触面 ②）
CONTRACTS_DIR = REPO / "contracts"
SPEC_TEMPLATE = REPO / "rules" / "spec-template-v2.json"


def ensure_dirs() -> None:
    for d in (BIDMASTER_HOME, AGENT_QUEUE_DIR, DIGEST_DIR, DIGEST_TMP, LEADS_DIR):
        d.mkdir(parents=True, exist_ok=True)
