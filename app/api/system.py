#!/usr/bin/env python3
"""app/api/system.py · 系统运维域

digest 重算 + 全量重置——高危运维操作集中在此域。
beacon：客户端诊断信标（DEV-0068）——前端把点击流/JS 错误上报到日志文件，
用于排查"内嵌浏览器里按钮无反应"类不可见客户端问题。
"""
import json
import re
from datetime import date
from pathlib import Path

from .. import config
from ..services import notify
from ..store import app_db
import store as truth

_BEACON_LOG = Path(__file__).resolve().parent.parent.parent / "log" / "client-beacon.jsonl"
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def beacon(req):
    """客户端诊断信标：{event, detail?, build?} → 追加 log/client-beacon.jsonl。
    只写本地日志文件，不入库不入看板；字段限长去控制字符（防日志注入）。"""
    try:
        entry = {
            "ts": date.today().strftime("%Y-%m-%d") + " " + __import__("time").strftime("%H:%M:%S"),
            "event": _CTRL.sub("", str(req.body.get("event", "")))[:64],
            "detail": _CTRL.sub("", str(req.body.get("detail", "")))[:300],
            "build": _CTRL.sub("", str(req.body.get("build", "")))[:16],
        }
        _BEACON_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _BEACON_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return 200, {"ok": True}
    except Exception as e:
        return 200, {"ok": False, "err": str(e)[:120]}


def digest_regenerate(req):
    from ..services import digest_service
    target_date = req.body.get("date", "") or date.today().strftime("%Y-%m-%d")
    markdown, source, status = digest_service.regenerate(target_date)
    notify.log_module("digest", f"🔄 digest regenerate: date={target_date} source={source} status={status} len={len(markdown)}", "info")
    return 200, {"ok": True, "date": target_date, "markdown": markdown,
                 "source": source, "status": status, "regenerated": True, "length": len(markdown)}


def reset(req):
    """重置为 demo 数据（清全部标 + events → 重播 demo 标）。"""
    from ..bootstrap import seed_demo_bids
    for b in truth.load_bids():
        truth.delete_bid(b["bid_id"])
    _reset_events()
    seed_demo_bids()
    notify.log_sys("数据已重置", "info")
    return 200, {"ok": True}


def scheduler_status(req):
    """GET /api/v1/scheduler — 调度器状态（DEV-0081：3 小时一轮内置调度）。"""
    from ..services import scheduler
    return 200, {"ok": True, **scheduler.status()}


def scheduler_run(req):
    """POST /api/v1/scheduler/run — 手动触发一轮（后台线程执行，立即返回 202）。

    与自动轮次共用进程内锁：上一轮未结束时本请求返回 409。
    """
    from ..services import scheduler
    st = scheduler.status()
    if st.get("running"):
        return 409, {"ok": False, "err": "上一轮仍在执行，稍后再试"}
    if not st.get("enabled"):
        return 200, {"ok": False, "err": "调度器未启用（服务须以 start.sh 启动；BIDMASTER_SCHED_INTERVAL<=0 为禁用）"}
    import threading
    threading.Thread(target=scheduler.run_round, kwargs={"trigger": "manual"},
                     daemon=True, name="baw-scheduler-manual").start()
    return 202, {"ok": True, "note": "已触发一轮（后台执行），进度看 GET /api/v1/scheduler 或 sched-*.log"}


def _reset_events():
    import sqlite3
    conn = sqlite3.connect(str(config.APP_DB_PATH))
    conn.execute("DELETE FROM events")
    conn.commit()
    conn.close()
