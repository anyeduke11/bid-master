#!/usr/bin/env python3
"""app/services/agents.py · 智能体接触面服务（DEV-0042 五接触面 API 化）

①工单（ticket 状态机） ②契约/知识发现 ③产出登记（artifact.register/promote、run.register 命令）
④lessons 只读 ⑤观测（gate 阻塞查询 = set_stage --show 的 HTTP 形态）
"""
import io
import json
import contextlib
import sys
from pathlib import Path

from .. import config

sys.path.insert(0, str(config.REPO / "rules"))
import ticket as _ticket  # noqa: E402
import set_stage as _set_stage  # noqa: E402
import store as _store  # noqa: E402


# ────────────────────────── ① 工单 ──────────────────────────
def ticket_generate(template, bid_id="", round_no=1, stage=""):
    try:
        t = _ticket.create_ticket(template, bid_id, round_no, stage)
    except SystemExit as e:
        return {"ok": False, "err": str(e)}
    return {"ok": True, "ticket": t, "prompt": t.get("prompt", "")}


def ticket_list(status=""):
    rows = []
    if _ticket.QUEUE.exists():
        for p in sorted(_ticket.QUEUE.glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if status and d.get("status") != status:
                continue
            rows.append({"ticket_id": d.get("ticket_id"), "type": d.get("type"),
                         "status": d.get("status"), "bid_id": d.get("bid_id"),
                         "created_at": d.get("created_at")})
    return rows


def ticket_reconcile():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = _ticket.reconcile()
    return {"ok": rc == 0, "log": buf.getvalue()}


# ────────────────────────── ② 契约/知识发现 ──────────────────────────
def contracts_agents() -> list:
    out = []
    ca = config.CONTRACTS_DIR / "agents"
    for p in sorted(ca.glob("*.json")) if ca.exists() else []:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def contracts_artifacts() -> dict:
    """产物契约发现：kind → schema 摘要。"""
    out = {}
    ca = config.CONTRACTS_DIR / "artifact"
    for p in sorted(ca.glob("*.schema.json")) if ca.exists() else []:
        try:
            out[p.stem.replace(".schema", "")] = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
    return out


def lessons() -> list:
    """教训只读（真实层 lessons 表权威；写仍只经 apply_archive + 人工确认）。"""
    _store.init()
    c = _store._conn()
    return [dict(r) for r in c.execute("SELECT id, scenario, lesson, supersession, status, created_at FROM lessons ORDER BY id")]


def spec_template() -> dict:
    if config.SPEC_TEMPLATE.exists():
        return json.loads(config.SPEC_TEMPLATE.read_text(encoding="utf-8"))
    return {}


# ────────────────────────── ③ 产出登记（供命令层调用） ──────────────────────────
def artifact_register(bid_id, kind, path, status="registered", producer="main-agent") -> dict:
    _store.init()
    return _store.register_artifact(bid_id, kind, path, status=status, producer=producer)


def artifact_promote(bid_id, kind, path) -> dict:
    _store.init()
    return _store.promote_artifact(bid_id, kind, path)


def run_register(agent, bid_id=None, model="", duration_s=None, input_fingerprint=None,
                 ticket_id=None, self_check=None, tokens=None) -> dict:
    _store.init()
    return _store.register_run(agent=agent, bid_id=bid_id, model=model, duration_s=duration_s,
                               input_fingerprint=input_fingerprint, ticket_id=ticket_id,
                               self_check=self_check, tokens=tokens)


# ────────────────────────── ⑤ 观测：gate 阻塞查询 ──────────────────────────
def gate_query(bid_id: str) -> dict:
    """下一阶段门禁阻塞项查询（advance_payload 的只读变体：不落 gate_attempt、不写状态）。

    返回 {bid_id, from, to, ok, blockers, extra}；bid 不存在时 ok=False。
    """
    records = _set_stage._load_bids()
    rec = next((r for r in records if r.get("bid_id") == bid_id), None)
    if rec is None:
        return {"bid_id": bid_id, "from": None, "to": None, "ok": False,
                "blockers": [f"bid 不存在: {bid_id}"], "extra": {}}
    cur = rec.get("stage", "S0")
    idx = _set_stage.STAGES.index(cur)
    if idx + 1 >= len(_set_stage.STAGES):
        return {"bid_id": bid_id, "from": cur, "to": None, "ok": True,
                "blockers": ["已在终态 S9"], "extra": {}}
    to = _set_stage.STAGES[idx + 1]
    gate = _set_stage.GATES.get((cur, to))
    if gate is None:
        return {"bid_id": bid_id, "from": cur, "to": to, "ok": True,
                "blockers": [], "extra": {"note": "本迁移无门禁"}}
    ok, blockers, extra = gate(config.BIDMASTER_HOME / "bids" / bid_id, {"sign_off": ""})
    blockers = list(blockers)
    if (cur, to) == ("S5", "S6") and ok:
        blockers = ["缺人工放行签核：须以 --sign-off <姓名> 显式通过（L3 审批位，不可代签）"]
        ok = False
    return {"bid_id": bid_id, "from": cur, "to": to, "ok": ok, "blockers": blockers, "extra": extra}
