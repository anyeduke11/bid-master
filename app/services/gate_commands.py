#!/usr/bin/env python3
"""app/services/gate_commands.py · 门禁/工单/登记/剧本命令注册（自 server.py 1935-1999 迁移 + 智能体新增命令）"""
import io
import re
from contextlib import redirect_stdout

import set_stage as _set_stage  # rules/set_stage.py（S0–S9 唯一写入口，进程内调用）
from . import agents, playbooks
from .command_engine import register_command

_BID_RE = re.compile(r"[A-Za-z0-9._\-]{1,64}")  # 含点号——真实标 bid_id 形如 2026-REAL01-aqfw


def _cmd_bid_advance_stage(conn, params):
    """bid.advance_stage - BAW 状态推进（set-stage 门禁内嵌；拒绝返回卡点清单）。
    DEV-0070：ignore_material 透传（仅 S4→S5 素材门禁）；bid_id 正则补点号。"""
    bid_id = str(params.get("bid_id", ""))
    to = str(params.get("to_stage", params.get("to", "")))
    sign_off = str(params.get("sign_off", "") or "")
    ignore_material = str(params.get("ignore_material", "") or "")
    if not _BID_RE.fullmatch(bid_id):
        return {"ok": False, "err": f"非法 bid_id: {bid_id!r}（只允许字母/数字/./_/-，≤64 位）"}
    if to not in _set_stage.STAGES:
        return {"ok": False, "err": f"非法目标阶段: {to!r}（允许 {'/'.join(_set_stage.STAGES)}）"}
    if ignore_material and to != "S5":
        return {"ok": False, "err": "--ignore-material 仅适用于 S4→S5 素材门禁"}
    rc, out = _set_stage.advance_payload(bid_id, to, sign_off, ignore_material)
    out["rc"] = rc
    return out


def _cmd_bid_settle_material(conn, params):
    """bid.settle_material - 材料债复验销单（素材率≥80% 且零缺口 → 工单 done）。
    进程内调 set_stage.settle_material（stdout 捕获为文本，避免污染命令 JSON 响应）。"""
    bid_id = str(params.get("bid_id", ""))
    if not _BID_RE.fullmatch(bid_id):
        return {"ok": False, "err": f"非法 bid_id: {bid_id!r}"}
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = _set_stage.settle_material(bid_id)
    except Exception as e:
        return {"ok": False, "err": f"{type(e).__name__}: {e}"}
    return {"ok": rc == 0, "rc": rc, "output": buf.getvalue().strip()[-800:]}


def _cmd_ticket_generate(conn, params):
    return agents.ticket_generate(str(params.get("template", "")),
                                  str(params.get("bid_id", "") or ""),
                                  int(params.get("round", 1) or 1),
                                  str(params.get("stage", "") or ""))


def _cmd_ticket_list(conn, params):
    # DEV-0042 修复：原实现引用未定义的 _ticket（NameError），现统一走 agents 服务
    return {"ok": True, "tickets": agents.ticket_list(str(params.get("status", "") or ""))}


def _cmd_ticket_reconcile(conn, params):
    return agents.ticket_reconcile()


def _cmd_artifact_register(conn, params):
    try:
        r = agents.artifact_register(str(params.get("bid_id", "")), str(params.get("kind", "")),
                                     str(params.get("path", "")),
                                     status=str(params.get("status", "registered")),
                                     producer=str(params.get("producer", "main-agent")))
        return r
    except FileNotFoundError as e:
        return {"ok": False, "err": f"产物文件不存在: {e}"}
    except ValueError as e:
        return {"ok": False, "err": str(e)}


def _cmd_artifact_promote(conn, params):
    r = agents.artifact_promote(str(params.get("bid_id", "")), str(params.get("kind", "")),
                                str(params.get("path", "")))
    return r


def _cmd_run_register(conn, params):
    return agents.run_register(
        agent=str(params.get("agent", "")),
        bid_id=params.get("bid_id") or None,
        model=str(params.get("model", "") or ""),
        duration_s=params.get("duration_s"),
        input_fingerprint=params.get("input_fingerprint"),
        ticket_id=params.get("ticket_id"),
        self_check=params.get("self_check"),
        tokens=params.get("tokens"),
    )


def _cmd_playbook_run(conn, params):
    return playbooks.run_in_command(conn, params)


def register_all():
    register_command("bid.advance_stage", "gate", _cmd_bid_advance_stage,
                     "BAW 状态推进（set-stage 门禁内嵌，拒绝返回卡点清单）",
                     schema={"bid_id": "str(≤64 字母数字._-)", "to_stage": "S0..S9", "sign_off": "str(S5→S6 必填)",
                             "ignore_material": "str(仅 S4→S5，素材门禁忽略原因)"})
    register_command("bid.settle_material", "gate", _cmd_bid_settle_material,
                     "材料债复验销单（素材率≥80% 且零缺口 → 材料债工单 done）",
                     schema={"bid_id": "str"})
    register_command("ticket.generate", "platform", _cmd_ticket_generate,
                     "生成提示词工单（params: template/bid_id/round/stage）",
                     schema={"template": "rules/tickets/<name>", "bid_id": "str", "round": "int", "stage": "str"})
    register_command("ticket.list", "platform", _cmd_ticket_list,
                     "工单队列列表（params: status 可选）", schema={"status": "str?"})
    register_command("ticket.reconcile", "platform", _cmd_ticket_reconcile,
                     "工单对账消单（ticket_id ↔ 产物 manifest/runs）")
    register_command("artifact.register", "agent", _cmd_artifact_register,
                     "产物登记（契约校验→指纹→落库；生产者自报 final 强制降级 registered）",
                     schema={"bid_id": "str", "kind": "stage0|hits_recon|completeness|spec|audit|locator|draft|...",
                             "path": "str", "status": "registered|final", "producer": "str"})
    register_command("artifact.promote", "agent", _cmd_artifact_promote,
                     "产物门禁提升 registered→final（指纹未变才提升）",
                     schema={"bid_id": "str", "kind": "str", "path": "str"})
    register_command("run.register", "agent", _cmd_run_register,
                     "run manifest 入库（工单回执权威来源）",
                     schema={"agent": "str", "bid_id": "str?", "model": "str?", "self_check": "str?",
                             "ticket_id": "str?", "tokens": "int?"})
    register_command("playbook.run", "platform", _cmd_playbook_run,
                     "跑剧本", schema={"id": "pb-*"})
