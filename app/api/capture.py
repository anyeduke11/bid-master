#!/usr/bin/env python3
"""app/api/capture.py · 标讯抓取/inbox 状态端点（L1 lead_capture 只读+触发）"""
import os
from datetime import datetime
from pathlib import Path

from .. import config


def inbox_status(req):
    """inbox/capture 状态（只读，不跑脚本）。"""
    raw_dir = config.BIDMASTER_HOME / "leads" / "raw"
    leads_jsonl = raw_dir / "leads.jsonl"
    log_path = config.BIDMASTER_HOME / "log" / "cron-capture.log"

    last_run_at = ""
    last_run_ok = False
    note = "未检测到抓取记录。"

    if log_path.exists():
        try:
            lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            if lines:
                last_line = lines[-1]
                last_run_at = last_line[:19] if len(last_line) >= 19 else last_line
                last_run_ok = "capture" in last_line and "成功" in last_line
                note = f"最近抓取：{last_line.strip()[:120]}"
        except Exception:
            pass

    if not last_run_at and leads_jsonl.exists():
        try:
            ts = datetime.fromtimestamp(leads_jsonl.stat().st_mtime)
            last_run_at = ts.strftime("%Y-%m-%d %H:%M:%S")
            note = f"inbox 文件最后更新：{last_run_at}"
        except Exception:
            pass

    pending = 0
    if leads_jsonl.exists():
        try:
            pending = sum(1 for _ in leads_jsonl.open("rb"))
        except Exception:
            pass

    try:
        script_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "lead_capture.sh"
        if script_path.exists():
            content = script_path.read_text(encoding="utf-8", errors="ignore")
            capture_engine = "crawl4ai" if "lead_capture_crawl4ai.py" in content else "legacy"
        else:
            capture_engine = "unknown"
    except Exception:
        capture_engine = "unknown"

    return 200, {
        "ok": True,
        "last_run_ok": last_run_ok,
        "last_run_at": last_run_at,
        "schedule": "服务内置调度器 3h 一轮（GET /api/v1/scheduler）",
        "pending_status_check": pending,
        "note": note,
        "capture_engine": capture_engine,
    }


def run_capture(req):
    """手动触发一次标讯抓取（后台 Popen，不阻塞响应）。"""
    import subprocess
    from ..services import notify

    repo = Path(__file__).resolve().parent.parent.parent
    script = repo / "scripts" / "lead_capture.sh"
    if not script.exists():
        return 200, {"ok": False, "err": f"抓取脚本不存在: {script}"}

    log_dir = config.BIDMASTER_HOME / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "cron-capture.log"

    try:
        lf = open(log_path, "a", encoding="utf-8")
        proc = subprocess.Popen(
            ["bash", str(script)],
            cwd=str(repo),
            stdout=lf,
            stderr=subprocess.STDOUT,
            close_fds=True,
        )
        lf.close()  # DEV-0081：父进程句柄即关（子进程持有继承的 fd；原实现每次泄漏一个）
        notify.log_module("capture", f"手动触发标讯抓取 PID={proc.pid}", "info")
        return 200, {"ok": True, "pid": proc.pid, "log": str(log_path)}
    except Exception as e:
        return 200, {"ok": False, "err": str(e)}
