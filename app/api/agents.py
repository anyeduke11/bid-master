#!/usr/bin/env python3
"""app/api/agents.py · 智能体五接触面域

①工单 GET /tickets
②契约发现 GET /contracts/agents /contracts/artifacts /lessons /spec-template
③产出登记 artifact.register/promote（经命令网关，见 commands 域）
④知识只读 GET /lessons
⑤运行时队列 GET /agent/queue + 问答 POST /agent/ask /agent/answer
"""
import json
from datetime import datetime

from .. import config
from ..services import bid_service, notify
import store as truth


def tickets(req):
    from ..services import agents
    status = req.query.get("status", [""])[0]
    return 200, {"ok": True, "tickets": agents.ticket_list(status)}


def contracts_agents(req):
    from ..services import agents
    return 200, {"ok": True, "agents": agents.contracts_agents()}


def contracts_artifacts(req):
    from ..services import agents
    return 200, {"ok": True, "schemas": agents.contracts_artifacts()}


def lessons(req):
    from ..services import agents
    return 200, {"ok": True, "lessons": agents.lessons()}


def spec_template(req):
    from ..services import agents
    return 200, {"ok": True, "template": agents.spec_template()}


def queue(req):
    """agent 请求队列（Mavis 消费）。"""
    if not config.AGENT_QUEUE_DIR.exists():
        return 200, []
    files = sorted(config.AGENT_QUEUE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    items = []
    for f in files[:20]:
        try:
            items.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return 200, items


def ask(req):
    """向 Mavis 排队一个问答请求。"""
    code = req.body.get("code", "")
    question = req.body.get("question", "")
    qtype = req.body.get("type", "summary")
    b = bid_service.find(code)
    if not b:
        return 404, {"err": f"客户不存在: {code}"}
    queue_dir = config.AGENT_QUEUE_DIR
    queue_dir.mkdir(parents=True, exist_ok=True)
    safe_code = "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in str(code))[:64]
    req_id = f"{safe_code}_{int(datetime.now().timestamp())}"
    req_file = queue_dir / f"{req_id}.json"
    req_data = {
        "id": req_id, "ts": datetime.now().isoformat(),
        "code": code, "client": b.get("client", ""),
        "type": qtype, "question": question,
        "context": {
            "stage": b.get("stage", ""), "priority": b.get("priority", ""),
            "industry": b.get("industry", ""), "region": b.get("region", ""),
            "ai_ready": b.get("ai_ready", []), "human_todo": b.get("human_todo", []),
            "block": b.get("block", ""), "due_at": b.get("due_at", ""),
        }
    }
    req_file.write_text(json.dumps(req_data, ensure_ascii=False, indent=2), encoding="utf-8")
    notify.log_module("agent", f"Mavis 收到 {qtype} 请求: {code}", "info", code)
    notify.sse.broadcast("agent_request", {"id": req_id, "code": code, "type": qtype})
    return 200, {"ok": True, "id": req_id, "msg": "已排队,等 Mavis 处理"}


def answer(req):
    """Mavis 写回回答到 bid 字段。"""
    code = req.body.get("code", "")
    field = req.body.get("field", "ai_summary")
    text = req.body.get("text", "")
    b = bid_service.find(code)
    if not b:
        return 404, {"err": f"客户不存在: {code}"}
    b[field] = text
    b["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bid_service.save_profile(b)
    notify.log_module("agent", f"Mavis 写回 {code}.{field}: {text[:60]}", "info", code)
    notify.sse.broadcast("agent_answer", {"code": code, "field": field})
    return 200, {"ok": True}
