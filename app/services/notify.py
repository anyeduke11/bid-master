#!/usr/bin/env python3
"""app/services/notify.py · 事件日志 + SSE 广播 + P0 看门狗（自 server.py 48-112/1412-1442 迁移）"""
import json
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from .. import config
from ..web.http import SSEHub
from ..store import app_db

sse = SSEHub()

# 内存事件缓冲（/api/v1/logs 与 /api/v1/initial 的数据源；SQLite 同步落盘）
EVENTS = []
EVENTS_LOCK = threading.Lock()
EVENTS_CAP = 500


def log_event(api, code, payload):
    ev = {"ts": datetime.now().strftime("%H:%M:%S") + "." + str(datetime.now().microsecond)[:2],
          "api": api, "code": code, "payload": payload, "type": "api"}
    _push(ev)
    app_db.save_event({**ev, "level": "info", "module": "api"})


def log_sys(msg, level="info"):
    ev = {"ts": datetime.now().strftime("%H:%M:%S"), "msg": msg, "level": level, "type": "sys"}
    _push(ev)


def log_module(module, msg, level="info", code="", payload=None):
    """模块化日志：区分 playbook / api / system / script，支持 level。内存 + jsonl + SQLite 三落盘。"""
    ev = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "." + str(datetime.now().microsecond)[:2],
        "module": module, "level": level, "code": code, "msg": msg,
        "payload": payload or {}, "type": "mod"
    }
    _push(ev)
    try:
        config.ensure_dirs()
        with open(config.LOG_JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 落盘失败不阻塞
    app_db.save_event(ev)


def _push(ev):
    with EVENTS_LOCK:
        EVENTS.insert(0, ev)
        del EVENTS[EVENTS_CAP:]


def load_events_into_memory(limit=200):
    """boot 时从 SQLite 恢复最近事件（跨重启可查）。"""
    rows = app_db.load_events(limit)
    if rows:
        with EVENTS_LOCK:
            EVENTS[:] = rows


def is_dummy_lark_config():
    """Lark 配置是否 placeholder/dummy（True 表示静默跳过）。"""
    if not config.LARK_CONFIG.exists():
        return True
    try:
        cfg = json.loads(config.LARK_CONFIG.read_text(encoding="utf-8"))
        url = cfg.get("webhook", "")
        if not url or not url.startswith(("http://", "https://")):
            return True
        if any(tag in url.lower() for tag in ("test_dummy", "example.com", "placeholder", "your-webhook")):
            return True
        return False
    except Exception:
        return True


def check_p0_alert(code, bid):
    """P0 看门狗：任意 P0 客户 stage/block 变化 → SSE 告警 + 飞书异步推送。"""
    if bid.get("priority") != "P0":
        return
    payload = {
        "code": code,
        "client": bid.get("client", ""),
        "stage": bid.get("stage", ""),
        "block": bid.get("block", ""),
        "msg": f"🚨 P0 告警 · {bid.get('client', '')} · {bid.get('stage', '')}" + (f" · {bid.get('block', '')}" if bid.get("block") else "")
    }
    sse.broadcast("p0_alert", payload)

    def _push_lark_async():
        if is_dummy_lark_config():
            return
        try:
            payload_json = json.dumps({**payload, "level": "warn",
                                       "detail": f"截止:{bid.get('due_at', '')} · AI:{len(bid.get('ai_ready', []))}项 · 阻塞:{bid.get('block', '') or '无'}"},
                                      ensure_ascii=False)
            proc = subprocess.run(
                ["bash", str(config.SCRIPTS_DIR / "lark_push.sh")],
                input=payload_json, capture_output=True, text=True, timeout=10
            )
            log_module("lark", f"P0 推送 {code}: {proc.stdout.strip()[:120]}", "info", code)
        except Exception as e:
            log_module("lark", f"P0 推送失败 {code}: {e}", "warn", code)

    threading.Thread(target=_push_lark_async, daemon=True).start()
