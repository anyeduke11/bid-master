#!/usr/bin/env python3
"""app/api/meta.py · 元/聚合/报表读端点（health/initial/stats/logs/summary/digest/bids-summary）"""
import time

from .. import config
from ..services import bid_service, digest_service, notify, summary as summary_svc
from ..store import app_db


def health(req):
    return 200, {"ok": True, "service": "bid-board", "port": config.PORT,
                 "bids": len(bid_service.all_bids("all")), "events": len(notify.EVENTS)}


def initial(req):
    """前端首载聚合（bids+stats+events+playbooks+flow_template）。"""
    from ..services import playbooks
    return 200, {
        "bids": bid_service.all_bids("active"),
        "stats": bid_service.stats(),
        "events": notify.EVENTS[:30],
        "playbooks": playbooks.meta(),
        "flow_template": bid_service.FLOW_TEMPLATE,
    }


def stats(req):
    return 200, bid_service.stats()


def bids_summary(req):
    summary = {"active": 0, "paused": 0, "closed": 0, "archived": 0, "total": 0}
    for b in bid_service.all_bids("all"):
        lc = b.get("lifecycle", "active")
        summary[lc] = summary.get(lc, 0) + 1
        summary["total"] += 1
    return 200, summary


def logs(req):
    qs = req.query
    limit = int(qs.get("limit", ["60"])[0])
    level = qs.get("level", [None])[0]
    module = qs.get("module", [None])[0]
    code = qs.get("code", [None])[0]
    keyword = qs.get("keyword", [None])[0]
    import json as _json
    events = notify.EVENTS[:]
    if level:
        events = [e for e in events if e.get("level") == level]
    if module:
        events = [e for e in events if e.get("module") == module or e.get("api", "").startswith(module)]
    if code:
        events = [e for e in events if e.get("code") == code]
    if keyword:
        kw = keyword.lower()
        events = [e for e in events if kw in _json.dumps(e, ensure_ascii=False).lower()]
    return 200, events[:limit]


def digest(req):
    qs = req.query
    target_date = qs.get("date", [time.strftime("%Y-%m-%d")])[0]
    force = qs.get("force", ["0"])[0] in ("1", "true", "yes")
    markdown, source, status = digest_service.get_or_generate(target_date, force=force)
    notify.log_module("digest", f"📋 digest GET: date={target_date} force={force} source={source} status={status} len={len(markdown)}", "info")
    return 200, {"ok": True, "date": target_date, "markdown": markdown,
                 "source": source, "status": status, "length": len(markdown)}


def summary(req):
    period = req.query.get("period", ["week"])[0]
    return 200, summary_svc.compute(period)
