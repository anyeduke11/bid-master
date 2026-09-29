#!/usr/bin/env python3
"""app/api/baw.py · BAW 观测域（bids/epoch/alerts/views/gate）

BAW 层只读投影：live bids、epoch 时钟、告警、管线视图、门禁阻塞查询。
全部只读 truth.db，不写入任何状态。
"""
import hashlib
import json
import re

from .. import config
import store as truth  # rules/store.py（真实层读模型）

# DEV-0068：前端版本握手——epoch 响应附带 index.html 内容指纹（mtime 缓存），
# 页面每 5s 轮询时比对内嵌 PAGE_BUILD，不一致即自动 location.reload()。
# 语义：服务端重启/前端更新后，所有打开的旧页面在 5 秒内自愈，不再依赖用户手动刷新。
_build_cache = {"mtime": None, "hash": ""}


def _frontend_build() -> str:
    p = config.PUBLIC_DIR / "index.html" if hasattr(config, "PUBLIC_DIR") else None
    if p is None:
        # config 无 PUBLIC_DIR 时按服务根推导（server.py 在仓库根起服）
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent.parent / "public" / "index.html"
    try:
        m = p.stat().st_mtime
        if _build_cache["mtime"] != m:
            _build_cache["mtime"] = m
            _build_cache["hash"] = "b" + hashlib.sha256(p.read_bytes()).hexdigest()[:8]
        return _build_cache["hash"]
    except OSError:
        return "unknown"


def _re_fullmatch(pat, s):
    return re.fullmatch(pat, s) is not None


def bids(req):
    """BAW live bids（truth.db 直读，baw-live-1 形状；管线视图数据源）。"""
    try:
        rows = [{"bid_id": b["bid_id"], "stage": b["stage"], "kind": b.get("kind", ""),
                 "note": b.get("note", ""), "updated_at": b.get("updated_at", "")}
                for b in truth.load_bids()]
        return 200, {"ok": True, "bids": rows, "schema": "baw-live-1"}
    except Exception as e:
        return 200, {"ok": True, "bids": [], "note": f"真实层读取失败: {e}"}


def epoch(req):
    return 200, {"ok": True, "epoch": truth.get_epoch(), "build": _frontend_build()}


def alerts(req):
    try:
        d = json.loads(config.ALERTS_JSON.read_text(encoding="utf-8"))
        return 200, {"ok": True, "alerts": d.get("alerts", []),
                     "generated_at": d.get("generated_at", "")}
    except Exception as e:
        return 200, {"ok": True, "alerts": [],
                     "note": f"alerts.json 尚未生成（{type(e).__name__}）"}


def view(req):
    name = req.params["name"]
    if name == "now":
        return 200, {"ok": True, "view": "now", "data": truth.read_now()}
    if name == "funnel":
        return 200, {"ok": True, "view": "funnel", "data": truth.read_funnel()}
    if name == "system":
        return 200, {"ok": True, "view": "system", "data": truth.read_system()}
    return 404, {"err": f"未知视图: {name}"}


def view_bid(req):
    bid_id = req.params["bid_id"]
    if not _re_fullmatch(r"[A-Za-z0-9_\-]{1,80}", bid_id):
        return 400, {"ok": False, "err": "非法 bid_id"}
    return 200, {"ok": True, "view": "bid", "data": truth.read_bid_detail(bid_id)}


def gate_query(req):
    """门禁阻塞项查询 = set_stage --show 的 HTTP 形态（只读，不写 gate_attempt）。"""
    from ..services import agents
    bid_id = req.params["bid_id"]
    if not _re_fullmatch(r"[A-Za-z0-9_\-]{1,64}", bid_id):
        return 400, {"ok": False, "err": "非法 bid_id"}
    return 200, agents.gate_query(bid_id)
