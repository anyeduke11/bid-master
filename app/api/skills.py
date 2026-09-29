#!/usr/bin/env python3
"""app/api/skills.py · 技能/剧本域

技能状态查询 + 异步执行 + 剧本列表 + 剧本执行 + 执行记录查询。
技能和剧本是 zcode 智能体的人工编排层——可通过 HTTP 触发而非 CLI。
"""
from ..services import notify, playbooks, skills
from ..store import app_db


def status(req):
    return 200, {"skills": skills.status()}


def run(req):
    """POST /api/v1/skills/run — 异步执行技能（透传 bid_id + agent_id）。"""
    skill_id = req.body.get("skill", "") or req.query.get("skill", [""])[0]
    bid_id = req.body.get("bid_id", "") or None
    agent_id = req.body.get("agent_id", "kanban")
    ok, payload = skills.run_async(skill_id, bid_id, agent_id)
    if not ok:
        if "未知" in str(payload.get("err", "")):
            return 400, payload
        return 404, payload
    return 202, payload


def playbooks_list(req):
    return 200, playbooks.meta()


def playbooks_run(req):
    """POST /api/v1/playbooks/run — 执行剧本（透传 bid_id + agent_id）。"""
    pb_id = req.body.get("id", "")
    bid_id = req.body.get("bid_id", "") or None
    agent_id = req.body.get("agent_id", "kanban")
    ok, payload = playbooks.run(pb_id, bid_id, agent_id)
    if not ok:
        return 404, payload
    return 202, payload


def list_runs(req):
    """GET /api/v1/skills/runs — 列出执行记录（可选 ?bid_id=xxx 过滤）。"""
    bid_id = req.query.get("bid_id", [None])[0]
    limit = int(req.query.get("limit", ["20"])[0])
    runs = app_db.list_skill_runs(bid_id=bid_id, limit=limit)
    return 200, {"runs": runs, "total": len(runs)}


def get_run(req):
    """GET /api/v1/skills/runs/{run_id} — 单条执行详情。"""
    run_id = req.params.get("run_id", "")  # DEV-0081：Router 注入的属性名是 params（原 path_params 必 500）
    run = app_db.get_skill_run(run_id)
    if not run:
        return 404, {"err": f"执行记录不存在: {run_id}"}
    return 200, run


def activity(req):
    """GET /api/v1/activity — 统一活动日志（可选 ?target_id=xxx 过滤）。"""
    target_id = req.query.get("target_id", [None])[0]
    target_type = req.query.get("target_type", [None])[0]
    limit = int(req.query.get("limit", ["50"])[0])
    items = app_db.list_activity(target_id=target_id, target_type=target_type, limit=limit)
    return 200, {"activity": items, "total": len(items)}


def next_actions_sync(req):
    """POST /api/v1/next-actions/sync — zcode 全量同步智能建议（快照替换）。

    body: {"actions": [{bid_id, label, skill?, playbook?, icon?, reason?}], "source": "zcode"}
    """
    actions = req.body.get("actions")
    if not isinstance(actions, list):
        return 400, {"err": "body.actions 必须是数组"}
    cleaned = []
    for a in actions:
        if not a.get("bid_id") or not a.get("label"):
            return 400, {"err": f"action 缺 bid_id/label: {a}"}
        cleaned.append(a)
    source = req.body.get("source", "zcode")
    n = app_db.sync_next_actions(cleaned, source=source)
    from ..services import bid_service
    bid_service.invalidate_next_actions_cache()
    notify.log_event("next_actions.sync", "", {"count": n, "source": source})
    notify.sse.broadcast("next_actions_synced", {"count": n, "source": source})
    return 200, {"ok": True, "synced": n, "source": source}


def next_actions_list(req):
    """GET /api/v1/next-actions — 当前智能建议快照。"""
    return 200, {"actions": list(app_db.list_next_actions().values())}
