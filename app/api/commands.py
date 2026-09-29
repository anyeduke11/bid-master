#!/usr/bin/env python3
"""app/api/commands.py · 命令网关端点（写唯一通道）+ 注册表 + 审计查询"""
from ..services import command_engine
from ..store import app_db


def post_command(req):
    command_id = req.body.get("commandId", "")
    params = req.body.get("params", {})
    idem_key = req.headers.get("Idempotency-Key", "")
    payload_hash = req.headers.get("Payload-Hash", "")
    agent_id = req.headers.get("X-Agent-Id", "duke")
    if not command_id:
        return 400, {"err": "缺 commandId"}
    code, result, eid = command_engine.dispatch(command_id, params, idem_key or None,
                                                payload_hash or None, agent_id)
    return code, result


def list_commands(req):
    return 200, {"commands": command_engine.registry_view()}


def get_execution(req):
    eid = req.params["exec_id"]
    row = app_db.get_execution(eid)
    if not row:
        return 404, {"err": f"execution_id 不存在: {eid}"}
    import json as _json
    try:
        row["params"] = _json.loads(row["params"]) if row["params"] else {}
    except Exception:
        pass
    try:
        row["result"] = _json.loads(row["result"]) if row["result"] else None
    except Exception:
        pass
    return 200, row
