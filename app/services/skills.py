#!/usr/bin/env python3
"""app/services/skills.py · 通用 Skill 状态与执行（DEV-0043）

设计原则：通用 skill，不按客户/项目拆分——bid_id 是运行时参数，不是 skill 身份。
5 个通用 skill 对应 L1-L5 生命周期阶段，看板根据 bid 的 ltc_stage 自动建议。
执行过程有持久化记录（skill_runs 表）+ SSE 实时通知。
"""
import json
import secrets
import subprocess
import threading
import time
from datetime import datetime

from .. import config
from ..store import app_db
from . import notify

# 外部脚本映射（inline skill 不在此表，走 _run_inline）
SKILL_SCRIPTS = {
    "lead_capture": "lead_capture.sh",
    "qualify": "qualify_score.py",
    "delivery_extract": "delivery_extract.py",
    "archive_close": "archive_close.py",
}

SKILL_META = [
    {"id": "lead_capture", "name": "标讯抓取", "icon": "📡",
     "file": "lead_capture.sh", "schedule": "cron 10:30", "stage": "L1"},
    {"id": "qualify", "name": "资质评分", "icon": "🎯",
     "file": "qualify_score.py", "schedule": "按需", "stage": "L2"},
    {"id": "bid_seal", "name": "封标流水线", "icon": "📦",
     "file": None, "schedule": "按需", "stage": "L3", "params": {"bid_id": "required"}},
    {"id": "delivery_extract", "name": "合同抽取", "icon": "📄",
     "file": "delivery_extract.py", "schedule": "中标后", "stage": "L4", "params": {"bid_id": "required"}},
    {"id": "archive_close", "name": "归档", "icon": "📦",
     "file": "archive_close.py", "schedule": "关单后", "stage": "L5", "params": {"bid_id": "required"}},
]


def status() -> list:
    skills = []
    for s in SKILL_META:
        s = dict(s)
        if s.get("file"):
            script = config.SCRIPTS_DIR / s["file"]
            s["available"] = script.exists()
        else:
            s["available"] = True  # inline skill 总是可用
        s["last_run_hint"] = "可立即跑" if s["available"] else "脚本缺失"
        skills.append(s)
    return skills


def _run_inline_seal(bid_id, agent_id):
    """bid_seal 通用封标流水线：3+1 步走命令网关。任一步失败即 raise（run 记 failed）。

    ai_ready 走专用命令 bid.add_ai_ready（update_field 白名单不含数组字段）；
    block 走 bid.update_field。
    """
    from . import command_engine
    steps = [
        ("bid.add_ai_ready", "item", "审查完成"),
        ("bid.update_field", "value", "报价签字"),  # field=block
        ("bid.add_ai_ready", "item", "封标完成"),
    ]
    log = []
    for cmd_id, param_key, value in steps:
        params = {"code": bid_id, param_key: value}
        if cmd_id == "bid.update_field":
            params["field"] = "block"
        code, resp, eid = command_engine.dispatch(
            cmd_id, params,
            idempotency_key=f"seal-{bid_id}-{param_key}-{int(time.time())}-{secrets.token_hex(2)}",
            agent_id=agent_id, _internal=True)
        log.append({"cmd": cmd_id, "value": value, "status": code})
        if code >= 400:
            raise RuntimeError(f"{cmd_id} 失败({code}): {resp.get('err') if isinstance(resp, dict) else resp}")
    # 第 4 步：清 block
    code, resp, eid = command_engine.dispatch(
        "bid.update_field",
        {"code": bid_id, "field": "block", "value": ""},
        idempotency_key=f"seal-{bid_id}-clear-{int(time.time())}-{secrets.token_hex(2)}",
        agent_id=agent_id, _internal=True)
    log.append({"cmd": "bid.update_field(block='')", "value": "", "status": code})
    if code >= 400:
        raise RuntimeError(f"bid.update_field block 清除失败({code}): {resp.get('err') if isinstance(resp, dict) else resp}")
    return {"steps": len(log), "log": log}


def run_async(skill_id, bid_id=None, agent_id="kanban"):
    """后台执行 Skill——创建执行记录 + SSE 通知 + 完成回写。

    对外部脚本：bid_id 作为 args 传入。
    对 inline skill（bid_seal）：在进程内调命令网关。
    返回 (ok, payload)，其中 payload 含 run_id 供前端追踪。
    """
    # 验证 skill 存在
    meta = next((s for s in SKILL_META if s["id"] == skill_id), None)
    if not meta:
        return False, {"err": f"未知 skill: {skill_id}", "valid": [s["id"] for s in SKILL_META]}

    # 检查 bid_id 是否必须
    if meta.get("params", {}).get("bid_id") == "required" and not bid_id:
        return False, {"err": f"skill {skill_id} 需要 bid_id 参数"}

    # 创建执行记录
    run_id = app_db.create_skill_run(skill_id, bid_id, agent_id, {"bid_id": bid_id})
    ts = datetime.now().strftime("%H:%M:%S")
    notify.sse.broadcast("skill_started", {"run_id": run_id, "skill": skill_id, "bid_id": bid_id or "", "ts": ts})

    def _execute():
        try:
            if skill_id in SKILL_SCRIPTS:
                # 外部脚本
                script_path = config.SCRIPTS_DIR / SKILL_SCRIPTS[skill_id]
                if not script_path.exists():
                    raise FileNotFoundError(f"脚本缺失: {SKILL_SCRIPTS[skill_id]}")
                args = [bid_id] if bid_id else []
                proc = subprocess.run(
                    ["bash" if script_path.suffix == ".sh" else "python3", str(script_path)] + args,
                    capture_output=True, text=True, timeout=60)
                result = {"rc": proc.returncode, "stdout": proc.stdout[-300:] if proc.stdout else "",
                          "stderr": proc.stderr[-300:] if proc.stderr else ""}
                if proc.returncode != 0:
                    raise RuntimeError(f"rc={proc.returncode}")
            elif skill_id == "bid_seal":
                # inline 封标流水线
                result = _run_inline_seal(bid_id, agent_id)
            else:
                raise ValueError(f"skill {skill_id} 无执行路径")

            # 成功
            app_db.complete_skill_run(run_id, "completed", result)
            notify.log_module("skill", f"✓ {skill_id} 完成 run={run_id} bid={bid_id or ''}", "info", bid_id or "")
            notify.sse.broadcast("skill_completed", {"run_id": run_id, "skill": skill_id, "bid_id": bid_id or "", "status": "completed", "ts": datetime.now().strftime("%H:%M:%S")})
        except Exception as e:
            # 失败
            app_db.complete_skill_run(run_id, "failed", {"err": str(e)})
            notify.log_module("skill", f"✗ {skill_id} 失败 run={run_id} err={e}", "warn", bid_id or "")
            notify.sse.broadcast("skill_failed", {"run_id": run_id, "skill": skill_id, "bid_id": bid_id or "", "err": str(e), "ts": datetime.now().strftime("%H:%M:%S")})

    threading.Thread(target=_execute, daemon=True).start()
    return True, {"ok": True, "skill": skill_id, "bid_id": bid_id, "run_id": run_id, "msg": "已提交,后台执行"}
