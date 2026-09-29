#!/usr/bin/env python3
"""app/api/kb.py · 资产台账域（DEV-0081：补齐前端 07 视图一直在请求的 kb 端点）

数据源：truth.db kb_assets 表（权威，kb/index/*.json 降为导出）+ alerts.json（consistency 产出）。
只读；L3 红线：kb 只存元数据与文件指针（kb_init 契约），本域不暴露 raw 原文。
"""
import json

import store as truth

from .. import config
from ..services import notify


def _items(req, domain: str, key: str):
    try:
        rows = truth.kb_assets_by_domain(domain)
        items = [{"id": r.get("id", ""), "name": r.get("name", "") or r.get("id", ""),
                  "expiry": (r.get("valid_until") or r.get("updated_at") or "")[:10],
                  "owner": "", "status": r.get("status", "")}
                 for r in rows]
        return 200, {"ok": True, key: items, "source": "truth.db kb_assets"}
    except Exception as e:
        notify.log_module("kb", f"读取 {domain} 失败: {e}", "warn")
        return 200, {"ok": False, key: [], "source": "truth.db kb_assets", "err": str(e)[:120]}


def cert(req):
    return _items(req, "certs", "certs")


def people(req):
    return _items(req, "people", "people")


def case(req):
    return _items(req, "cases", "cases")


def solution(req):
    return _items(req, "solutions", "solutions")


def alerts(req):
    """kb 预警（consistency.py 产出的 alerts.json 投影为前端期望的 {level,title,due} 形状）。"""
    try:
        path = config.ALERTS_JSON
        if not path.exists():
            return 200, {"ok": True, "alerts": []}
        data = json.loads(path.read_text(encoding="utf-8"))
        out = [{"level": "danger" if a.get("severity") == "高" else "warn",
                "title": a.get("detail") or a.get("name") or str(a.get("type", "")),
                "due": str(a.get("item") or "")}
               for a in data.get("alerts", [])]
        return 200, {"ok": True, "alerts": out}
    except Exception as e:
        return 200, {"ok": False, "alerts": [], "err": str(e)[:120]}
