#!/usr/bin/env python3
"""app/services/bid_commands.py · bid.* 命令处理器（自 server.py 1466-1633 迁移，写经 bid_service→truth.db）"""
import json
from datetime import date, datetime

from . import bid_service, notify
from .command_engine import register_command


def _cmd_bid_update_field(conn, params):
    """bid.update_field - 改 block / priority / due_at / client / provenance（stage 收归门禁）
    R4（工程审查 2026-09-19）：provenance=涉密壳来历登记（"实际怎么来的"），写 profile + 事件留痕。"""
    code = params.get("code", "")
    field = params.get("field", "")
    value = params.get("value", "")
    reason = params.get("reason", "")
    if field not in ("block", "priority", "due_at", "client", "provenance"):
        return {"err": f"不支持的字段: {field}"}
    if field == "stage":
        return {"ok": False, "err": "stage 字段已收归门禁：请走 bid.advance_stage（set-stage 内嵌校验，拒绝返回卡点清单）",
                "blocked_by": "baw-gate", "hint": {"commandId": "bid.advance_stage", "params": {"bid_id": code, "to": value}}}
    b = bid_service.find(code)
    if not b:
        return {"err": f"客户不存在: {code}"}
    old = b.get(field)
    b[field] = value
    b["last_sync"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    b["updated_at"] = b["last_sync"]
    if field in ("block", "priority", "provenance"):
        hist = json.loads(b.get("lifecycle_history") or "[]")
        hist.append({"ts": b["updated_at"], "field": field, "old": old, "new": value, "reason": reason})
        b["lifecycle_history"] = json.dumps(hist, ensure_ascii=False)
    bid_service.save_profile(b)
    if field == "provenance":
        notify.log_event("update.provenance", code, {"value": str(value)[:200]})
    return {"ok": True, "code": code, "field": field, "old": old, "new": value}


def _cmd_bid_add_ai_ready(conn, params):
    code = params.get("code", "")
    item = params.get("item", "")
    if not item:
        return {"err": "缺 item"}
    b = bid_service.find(code)
    if not b:
        return {"err": f"客户不存在: {code}"}
    arr = b.setdefault("ai_ready", [])
    added = False
    if item not in arr:
        arr.append(item)
        added = True
    b["last_sync"] = b["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bid_service.save_profile(b)
    return {"ok": True, "added": added, "count": len(arr)}


def _cmd_bid_add_human_todo(conn, params):
    code = params.get("code", "")
    item = params.get("item", "")
    if not item:
        return {"err": "缺 item"}
    b = bid_service.find(code)
    if not b:
        return {"err": f"客户不存在: {code}"}
    arr = b.setdefault("human_todo", [])
    added = False
    if item not in arr:
        arr.append(item)
        added = True
    b["last_sync"] = b["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bid_service.save_profile(b)
    return {"ok": True, "added": added, "count": len(arr)}


def _cmd_bid_lifecycle(conn, params):
    """bid.lifecycle - 状态机推进（active/paused/closed/archived）"""
    code = params.get("code", "")
    new_status = params.get("to", "")
    reason = params.get("reason", "")
    loss_reason = params.get("loss_reason", "")
    if new_status not in ("active", "paused", "closed", "archived"):
        return {"err": f"非法状态: {new_status}"}
    b, err = bid_service.lifecycle_set(code, new_status, reason=reason,
                                       final_outcome=params.get("final_outcome", ""),
                                       loss_reason=loss_reason)
    if err:
        return {"err": err}
    try:
        hist = json.loads(b.get("lifecycle_history") or "[]")
        old = hist[-1]["from"] if hist else "active"
    except Exception:
        old = "active"
    return {"ok": True, "from": old, "to": new_status, "code": code}


def _cmd_bid_attach_summary(conn, params):
    """bid.attach_summary - Mavis 写 AI 摘要（必须带 author/evidence_refs）"""
    code = params.get("code", "")
    text = params.get("text", "")
    author = params.get("author", "mavis")
    summary_type = params.get("summary_type", "ai_reference")
    evidence_refs = params.get("evidence_refs", [])
    b = bid_service.find(code)
    if not b:
        return {"err": f"客户不存在: {code}"}
    if not text:
        return {"err": "缺 text"}
    if summary_type == "ai_reference" and not author:
        return {"err": "AI 摘要必须填 author"}
    summaries = json.loads(b.get("ai_summaries") or "[]")
    entry = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": summary_type, "author": author,
        "text": text[:2000],
        "evidence_refs": evidence_refs if isinstance(evidence_refs, list) else [evidence_refs],
        "commandId": params.get("_command_id", ""),
    }
    summaries.insert(0, entry)
    b["ai_summaries"] = json.dumps(summaries[:5], ensure_ascii=False)
    b["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bid_service.save_profile(b)
    return {"ok": True, "summaries_count": len(summaries[:5])}


def _cmd_bid_flow_node(conn, params):
    """bid.flow_node - 改流程节点（必须带 status；blocked_node 自动推导）"""
    code = params.get("code", "")
    node_id = params.get("node_id", "")
    status = params.get("status", "")
    block_reason = params.get("block_reason", "")
    b = bid_service.find(code)
    if not b:
        return {"err": f"客户不存在: {code}"}
    found = None
    for n in b.get("flow", {}).get("nodes", []):
        if n["id"] == node_id:
            n["status"] = status
            if status == "done":
                n["actual_end"] = date.today().strftime("%Y-%m-%d")
            if status == "blocked":
                n["block_reason"] = block_reason or "未说明"
            found = n
            break
    if not found:
        return {"err": f"node 不存在: {node_id}"}
    b["flow"]["blocked_node"] = next((nn["id"] for nn in b["flow"]["nodes"] if nn["status"] == "blocked"), None)
    b["last_sync"] = b["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bid_service.save_profile(b)
    return {"ok": True, "blocked_node": b["flow"]["blocked_node"]}


def _cmd_bid_create(conn, params):
    """bid.create - 新建 bid（truth.db 建档 + 看板 profile）"""
    code = params.get("code", "")
    if not code:
        return {"err": "缺 code"}
    if bid_service.find(code):
        return {"err": f"code 已存在: {code}"}
    new = bid_service.create(params)
    if not new:
        return {"err": "create 失败"}
    return {"ok": True, "code": code}


def _cmd_bid_delete(conn, params):
    """bid.delete - 手动删除 bid（truth + profile 物理删除）"""
    code = params.get("code", "")
    if not code:
        return {"err": "缺 code"}
    if not bid_service.find(code):
        return {"err": f"客户不存在: {code}"}
    bid_service.delete(code)
    return {"ok": True, "code": code, "deleted": True}


def register_all():
    register_command("bid.update_field", "platform", _cmd_bid_update_field,
                     "改 bid 字段(block/priority/due_at/client/provenance)；stage 收归门禁", idempotent=False,
                     schema={"code": "str", "field": "block|priority|due_at|client|provenance", "value": "any"})
    register_command("bid.add_ai_ready", "platform", _cmd_bid_add_ai_ready,
                     "追加 AI 完成项", schema={"code": "str", "item": "str"})
    register_command("bid.add_human_todo", "platform", _cmd_bid_add_human_todo,
                     "追加人工 todo", schema={"code": "str", "item": "str"})
    register_command("bid.lifecycle", "lifecycle", _cmd_bid_lifecycle,
                     "状态机推进(active/paused/closed/archived)", idempotent=False,
                     schema={"code": "str", "to": "active|paused|closed|archived", "reason": "str"})
    register_command("bid.attach_summary", "summary", _cmd_bid_attach_summary,
                     "Mavis 写 AI 摘要(必须 author + evidence_refs)",
                     schema={"code": "str", "text": "str", "author": "str", "evidence_refs": "list"})
    register_command("bid.flow_node", "platform", _cmd_bid_flow_node,
                     "改流程节点", schema={"code": "str", "node_id": "str", "status": "pending|progress|done|blocked"})
    register_command("bid.create", "platform", _cmd_bid_create,
                     "新建 bid（truth.db 建档 + 看板 profile；kind 自动判定，或显式 classified 壳+起步 stage）",
                     schema={"code": "str", "client": "str", "priority": "P0|P1|P2", "due_at": "YYYY-MM-DD HH:MM",
                             "kind": "real|classified（缺省自动判定）", "stage": "S0..S9（仅 classified 生效，R2）"})
    register_command("bid.delete", "platform", _cmd_bid_delete,
                     "删除 bid（truth + profile 物理删除）", schema={"code": "str"})
