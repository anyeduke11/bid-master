#!/usr/bin/env python3
"""app/services/playbooks.py · 通用剧本（DEV-0043）

设计原则：通用 playbook，不按客户/项目拆分——bid_id 是运行时参数。
5 个通用 playbook 对应 L1-L5 生命周期阶段。
执行过程有持久化记录（skill_runs 表）+ SSE 实时通知。
"""
import secrets
import subprocess
import threading
import time
from datetime import datetime

from .. import config
from ..store import app_db
from . import bid_service, notify


def _run_inline_seal(bid_id, agent_id):
    """pb-seal 通用封标流水线：3+1 步走命令网关。任一步失败即 raise（run 记 failed）。

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
            idempotency_key=f"pb-seal-{bid_id}-{param_key}-{int(time.time())}-{secrets.token_hex(2)}",
            agent_id=agent_id, _internal=True)
        log.append({"cmd": cmd_id, "value": value, "status": code})
        if code >= 400:
            raise RuntimeError(f"{cmd_id} 失败({code}): {resp.get('err') if isinstance(resp, dict) else resp}")
    # 第 4 步：清 block
    code, resp, eid = command_engine.dispatch(
        "bid.update_field",
        {"code": bid_id, "field": "block", "value": ""},
        idempotency_key=f"pb-seal-{bid_id}-clear-{int(time.time())}-{secrets.token_hex(2)}",
        agent_id=agent_id, _internal=True)
    log.append({"cmd": "bid.update_field(block='')", "value": "", "status": code})
    if code >= 400:
        raise RuntimeError(f"bid.update_field block 清除失败({code}): {resp.get('err') if isinstance(resp, dict) else resp}")
    return {"steps": len(log), "log": log}


PLAYBOOKS = [
    {"id": "pb-collect", "name": "L1 标讯采集跑完",
     "desc": "L1 标讯抓取 → 写入 leads 数据面",
     "stage": "L1", "script": "scripts/lead_capture.sh",
     "steps": [{"name": "拉 40+ 渠道标讯"}]},
    {"id": "pb-qualify", "name": "L2 资质预审 + AI 评分",
     "desc": "L2 资质预审(行业/区域/金额) + AI 关键词评分 → 写入 qualify.jsonl",
     "stage": "L2", "script": "scripts/qualify_score.py",
     "steps": [{"name": "资质 + 评分"}]},
    {"id": "pb-seal", "name": "L3 封标流水线",
     "desc": "L3 投标 · 3 步:审查 → 阻塞 → 封标（通用，bid_id 来自运行时参数）",
     "stage": "L3", "inline": True,
     "params": {"bid_id": "required"},
     "steps": [{"name": "审查完成"}, {"name": "阻塞:报价签字"}, {"name": "封标完成 + 清阻塞"}]},
    {"id": "pb-delivery", "name": "L4 合同要素抽取",
     "desc": "L4 交付 · 合同 PDF 抽取(合同号/金额/里程碑)",
     "stage": "L4", "script": "scripts/delivery_extract.py",
     "params": {"bid_id": "required"},
     "steps": [{"name": "合同要素抽取"}]},
    {"id": "pb-archive", "name": "L5 归档结案",
     "desc": "L5 归档 · close + 写归档文件",
     "stage": "L5", "script": "scripts/archive_close.py",
     "params": {"bid_id": "required"},
     "steps": [{"name": "close + 归档"}]},
]


def run(pb_id, bid_id=None, agent_id="kanban"):
    """跑剧本（外部脚本 / 内联步骤）——带执行记录 + SSE 通知。

    对外部脚本：bid_id 作为 args 传入（替代旧硬编码 args）。
    对 inline 剧本（pb-seal）：在进程内调命令网关。
    返回 (ok, payload)，其中 payload 含 run_id 供前端追踪。
    """
    pb = next((p for p in PLAYBOOKS if p["id"] == pb_id), None)
    if not pb:
        return False, {"err": f"playbook 不存在: {pb_id}"}

    if pb.get("params", {}).get("bid_id") == "required" and not bid_id:
        return False, {"err": f"playbook {pb_id} 需要 bid_id 参数"}

    # 创建执行记录
    run_id = app_db.create_skill_run(pb_id, bid_id, agent_id, {"bid_id": bid_id})
    ts = datetime.now().strftime("%H:%M:%S")
    notify.sse.broadcast("skill_started", {"run_id": run_id, "skill": pb_id, "bid_id": bid_id or "", "ts": ts})

    def _execute():
        try:
            if "script" in pb:
                script_path = config.REPO / pb["script"]
                if not script_path.exists():
                    raise FileNotFoundError(f"脚本不存在: {pb['script']}")
                args = [bid_id] if bid_id else pb.get("args", [])
                if script_path.suffix == ".sh":
                    proc = subprocess.run(
                        ["bash", str(script_path)] + args,
                        capture_output=True, text=True, timeout=30)
                else:
                    proc = subprocess.run(
                        ["python3", str(script_path)] + args,
                        capture_output=True, text=True, timeout=30)
                result = {"rc": proc.returncode,
                          "stdout": proc.stdout[-300:] if proc.stdout else "",
                          "stderr": proc.stderr[-300:] if proc.stderr else ""}
                if proc.returncode != 0:
                    raise RuntimeError(f"rc={proc.returncode}")
            elif pb.get("inline"):
                result = _run_inline_seal(bid_id, agent_id)
            else:
                raise ValueError(f"playbook {pb_id} 无执行路径")

            app_db.complete_skill_run(run_id, "completed", result)
            notify.log_module("playbook", f"✓ {pb_id} 完成 run={run_id} bid={bid_id or ''}", "info", bid_id or "")
            notify.sse.broadcast("skill_completed", {"run_id": run_id, "skill": pb_id, "bid_id": bid_id or "", "status": "completed", "ts": datetime.now().strftime("%H:%M:%S")})
        except Exception as e:
            app_db.complete_skill_run(run_id, "failed", {"err": str(e)})
            notify.log_module("playbook", f"✗ {pb_id} 失败 run={run_id} err={e}", "warn", bid_id or "")
            notify.sse.broadcast("skill_failed", {"run_id": run_id, "skill": pb_id, "bid_id": bid_id or "", "err": str(e), "ts": datetime.now().strftime("%H:%M:%S")})

    threading.Thread(target=_execute, daemon=True).start()
    return True, {"ok": True, "playbook": pb["name"], "bid_id": bid_id, "run_id": run_id, "msg": "已提交,后台执行"}


def run_in_command(conn, params):
    """playbook.run 命令处理器（内部串行,审计统一;嵌套命令不走 dispatch）。"""
    ok, payload = run(params.get("id", ""), params.get("bid_id", ""))
    return payload


def meta():
    return [{"id": p["id"], "name": p["name"], "desc": p["desc"],
             "stage": p["stage"],
             "params": p.get("params", {}),
             "steps": [{"name": s["name"]} for s in p["steps"]]} for p in PLAYBOOKS]
