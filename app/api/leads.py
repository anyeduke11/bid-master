#!/usr/bin/env python3
"""app/api/leads.py · lead 域端点（列表/关闭区/时效扫描）"""
from .. import config
from ..services import lead_store, notify


def list_leads(req):
    qs = req.query
    recommend = qs.get("recommend", [None])[0]
    limit = int(qs.get("limit", ["200"])[0])
    sort = qs.get("sort", [None])[0]
    order = qs.get("order", [None])[0]
    phase = qs.get("phase", [None])[0]
    from ..store import app_db
    leads = app_db.load_leads(limit=limit, recommend=recommend, sort=sort, order=order, phase=phase)
    return 200, {"leads": leads, "total": len(leads)}


def closed_leads(req):
    limit = int(req.query.get("limit", ["500"])[0])
    leads = lead_store.closed_leads(limit=limit)
    return 200, {
        "leads": leads,
        "total": len(leads),
        "filter": "expired",
        "msg": f"已过期 lead(> {config.LEAD_FRESH_DAYS} 天,关闭区)" if leads else "关闭区为空 — 所有 lead 都在时效内"
    }


def scan_freshness(req):
    try:
        result = lead_store.scan_lead_freshness(force_rescan=True)
        notify.log_module("lifecycle", f"🔍 lead 时效扫描: 扫描 {result['scanned']} 条 · 关闭 {len(result['expired'])} 条 · 老化 {len(result['aging'])} 条 · 跳已 promote {result.get('skip', 0)} 条", "info")
        return 200, {"ok": True, **result}
    except Exception as e:
        return 500, {"err": f"扫描失败: {e}"}
