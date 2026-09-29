#!/usr/bin/env python3
"""app/services/bid_service.py · 标域服务（看板字段 ∪ BAW 真实层，DEV-0042 统一模型）

数据模型：
  truth.db.bids          —— BAW 权威（bid_id/stage/kind，唯一写口 rules/store.py）
  truth.db.bid_profile   —— 看板运营字段（前端 24 字段形状 JSON，仍经 store 写口）
读：两表联查成「超集形状」；profile 缺失的 BAW 标合成最小看板行（管线卡可用）。
"""
import json
import uuid
from datetime import date, datetime, timedelta

import store as truth  # rules/store.py（真实层唯一写口）

from .. import config
from . import notify

# 流程模板（13 节点，自 server.py settings.flow_template 迁移）
FLOW_TEMPLATE = [
    {"id": "sales-bid", "name": "销售应标", "days_before_due": 30, "owner": "售前", "ai": ["bid-news-collection"]},
    {"id": "buy-rfp", "name": "购买标书", "days_before_due": 14, "owner": "商务", "ai": []},
    {"id": "quote", "name": "报价", "days_before_due": 10, "owner": "商务", "ai": ["quote-generation-v3"]},
    {"id": "case", "name": "准备案例", "days_before_due": 10, "owner": "售前", "ai": []},
    {"id": "qualification", "name": "人员资质", "days_before_due": 7, "owner": "HR", "ai": ["resume-builder"]},
    {"id": "tech-solution", "name": "技术方案", "days_before_due": 14, "owner": "技术", "ai": ["content-longform"]},
    {"id": "biz-solution", "name": "商务方案", "days_before_due": 10, "owner": "商务", "ai": ["content-longform"]},
    {"id": "draft", "name": "初稿", "days_before_due": 7, "owner": "技术", "ai": ["content-longform"]},
    {"id": "final", "name": "定稿", "days_before_due": 3, "owner": "PM", "ai": ["bid-file-review"]},
    {"id": "seal", "name": "封标", "days_before_due": 0, "owner": "PM", "ai": ["gate-checker"]},
    {"id": "present", "name": "讲标", "days_before_due": -1, "owner": "PM", "ai": []},
    {"id": "notice", "name": "公示", "days_before_due": -30, "owner": "商务", "ai": []},
    {"id": "retro", "name": "复盘", "days_before_due": -60, "owner": "PM", "ai": []},
]

LIFECYCLE_TRANSITIONS = {
    "active":   ["paused", "closed"],
    "paused":   ["active", "closed"],
    "closed":   ["active", "archived"],
    "archived": ["active"],  # 复活(罕见)
}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def find(code):
    """按 code（=bid_id）取超集形状 bid；不存在返回 None。
    profile 缺失的 BAW 标（真标不经看板建档）合成最小看板行——补齐默认字段，
    前端管线卡/深潜零特判。只读合成，不回写。"""
    profile = truth.get_bid_profile(code)
    trow = truth.get_bid(code)
    if profile is None and trow is None:
        return None
    if profile is not None:
        data = profile
    else:
        note = (trow.get("note") or "") if trow else ""
        data = {"client": note.split("（")[0].split(" ·")[0][:30] or code,
                "ai_ready": [], "human_todo": [], "block": "",
                "flow": {"blocked_node": None, "nodes": [{"id": t["id"], "status": "pending"} for t in FLOW_TEMPLATE]}}
    data.setdefault("code", code)
    # _enrich 两条路径都走：补默认字段 + 实时 next_action（zcode 建议 → 静态映射回退）
    _enrich(data, status=data.get("lifecycle", "active"))
    # BAW 权威字段（超集新增；kind/stage 权威来自 truth）
    data["bid_id"] = code
    data["kind"] = trow["kind"] if trow else "demo"
    truth_stage = trow["stage"] if trow else None
    data["stage"] = truth_stage if truth_stage else data.get("stage", "审查")
    return data


def all_bids(status="active"):
    """全部超集形状 bid（truth bids ∪ profile）。status: active|all|paused|closed|archived。"""
    truth_bids = {b["bid_id"]: b for b in truth.load_bids()}
    profiles = {p["code"]: p for p in truth.list_bid_profiles()}
    codes = sorted(set(truth_bids) | set(profiles))
    out = []
    for code in codes:
        b = find(code)
        if b is None:
            continue
        if status != "all" and b.get("lifecycle", "active") != status:
            continue
        out.append(b)
    return out


def stats():
    bids = all_bids("all")
    s = {"total": len(bids), "p0": 0, "p1": 0, "p2": 0, "ready": 0, "blocked": 0, "total_ai": 0}
    for b in bids:
        pri = b.get("priority", "P2")
        if pri in ("P0", "P1", "P2"):
            s[pri.lower()] = s.get(pri.lower(), 0) + 1
        s["total_ai"] += len(b.get("ai_ready", []) or [])
        if b.get("ai_ready"):
            s["ready"] += 1
        if b.get("block"):
            s["blocked"] += 1
    s["ready_rate"] = round(s["ready"] / max(s["total"], 1) * 100)
    return s


def create(bid_params):
    """新建标：truth.db 建档 + bid_profile 写看板形状。code 即 bid_id。
    R2（工程审查 2026-09-19）：kind 可显式传 classified（涉密壳），且壳可指定起步 stage
    ——仅 classified 生效（real/demo 仍强制 S0，门禁不可绕）。
    R6：壳走 slim profile——不生成 13 节点生产 flow（结构性噪音），_enrich 形状默认保留。"""
    code = bid_params.get("code", "")
    if not code:
        return None
    if find(code):
        return None
    today = date.today()
    due_str = bid_params.get("due_at", "")
    kind = str(bid_params.get("kind", "") or "")
    if kind:
        if kind not in truth.KINDS:
            return None
    else:
        kind = truth.kind_for(code)
    is_shell = kind == "classified"
    nodes = []
    if not is_shell:
        for t in FLOW_TEMPLATE:
            node = {"id": t["id"], "status": "pending"}
            if due_str and due_str != "持续":
                try:
                    due = datetime.strptime(due_str.split()[0], "%Y-%m-%d").date()
                    node["plan_end"] = (due - timedelta(days=t["days_before_due"])).isoformat()
                except (ValueError, IndexError):
                    node["plan_end"] = ""
            nodes.append(node)
    # R2：起步 stage——壳可从真实阶段入库，其余一律 S0
    start_stage = str(bid_params.get("stage", "") or "") if is_shell else ""
    if start_stage not in truth.STAGES:
        start_stage = "S0"
    new_bid = {
        "code": code, "client": bid_params.get("client", ""),
        "stage": bid_params.get("stage", "审查"),
        "priority": bid_params.get("priority", "P2"),
        "due_at": due_str,
        "ai_ready": bid_params.get("ai_ready", []),
        "human_todo": bid_params.get("human_todo", []),
        "block": bid_params.get("block", ""),
        "link": bid_params.get("link", ""),
        "last_sync": today.strftime("%Y-%m-%d %H:%M:%S"),
        "flow": {"blocked_node": None, "nodes": nodes},
        "ltc_stage": bid_params.get("ltc_stage", "bid"),
        "ai_summaries": json.dumps(bid_params.get("ai_summaries", []), ensure_ascii=False),
        "lifecycle_history": json.dumps([], ensure_ascii=False),
    }
    if is_shell:
        new_bid["classified"] = True   # 前端徽标 + slim 语义标记（元数据壳，零内容承诺）
    _enrich(new_bid, status=bid_params.get("lifecycle", "active"))
    for k in ("tier", "industry", "region", "competitors", "est_amount", "decision_maker", "partners"):
        if k in bid_params:
            new_bid[k] = bid_params[k]
    # 真实层建档（kind 显式或 store.kind_for 判定；起步 stage 见 R2）
    truth.create_bid(code, start_stage, bootstrapped=True, note=bid_params.get("note", "") or "看板建档", kind=kind)
    truth.upsert_bid_profile(code, new_bid)
    notify.sse.broadcast("bid_created", {"code": code, "client": bid_params.get("client", "")})
    return new_bid


def save_profile(b):
    truth.upsert_bid_profile(b["code"], b)


def set_field(code, field, value):
    """改字段（stage 冻结守卫保持）；数组字段字符串语义 = 追加。"""
    b = find(code)
    if not b:
        return None
    if field == "stage":
        raise ValueError("stage 字段已收归 BAW 门禁：请用 bid.advance_stage（set-stage 门禁，bid_id 为 2026-xxx 形态）")
    if field in ("ai_ready", "human_todo") and isinstance(value, str):
        arr = b.setdefault(field, [])
        if value not in arr:
            arr.append(value)
    else:
        b[field] = value
    b["last_sync"] = _now()
    b["updated_at"] = b["last_sync"]
    notify.log_event(f"update.{field}", code, {"value": value})
    save_profile(b)
    notify.sse.broadcast("bid_updated", {"code": code, "field": field, "value": value})
    return b


def lifecycle_set(code, new_status, reason="", final_outcome="", loss_reason=""):
    """设置 bid 生命周期状态（active/paused/closed/archived 状态机）。返回 (bid, err)。"""
    b = find(code)
    if not b:
        return None, f"客户不存在: {code}"
    old = b.get("lifecycle", "active")
    if old == new_status:
        return b, None
    if new_status not in LIFECYCLE_TRANSITIONS.get(old, []):
        return None, f"非法状态转换: {old} → {new_status}"
    now = _now()
    b["lifecycle"] = new_status
    if new_status == "paused":
        b["pause_reason"] = reason
        b["paused_at"] = now
    elif new_status == "active" and old == "paused":
        b["resumed_at"] = now
    elif new_status == "closed":
        b["closed_at"] = now
        b["close_reason"] = reason
        b["final_outcome"] = final_outcome
        if loss_reason:
            b["loss_reason"] = loss_reason
    elif new_status == "archived":
        b["archived_at"] = now
    b["updated_at"] = now
    hist = json.loads(b.get("lifecycle_history") or "[]")
    hist.append({"ts": now, "from": old, "to": new_status, "reason": reason, "loss_reason": loss_reason})
    b["lifecycle_history"] = json.dumps(hist, ensure_ascii=False)
    notify.log_event(f"lifecycle.{new_status}", code, {"from": old, "reason": reason,
                                                      "outcome": final_outcome, "loss_reason": loss_reason})
    notify.log_module("lifecycle", f"{code} {old} → {new_status}: {reason}" + (f" · loss={loss_reason}" if loss_reason else ""),
                      level="info", code=code)
    save_profile(b)
    notify.sse.broadcast("lifecycle", {"code": code, "from": old, "to": new_status,
                                       "reason": reason, "outcome": final_outcome, "loss_reason": loss_reason})
    return b, None


def auto_archive_check():
    """自动归档:closed + 30 天 → archived;active + 90 天无 sync → paused。"""
    today = date.today()
    archived, paused = [], []
    for b in all_bids("all"):
        lc = b.get("lifecycle", "active")
        if lc == "closed":
            closed_at = b.get("closed_at", "")
            if closed_at:
                try:
                    d = datetime.strptime(closed_at.split()[0], "%Y-%m-%d").date()
                    if (today - d).days >= 30:
                        b["lifecycle"] = "archived"
                        b["archived_at"] = _now()
                        b["updated_at"] = b["archived_at"]
                        notify.log_module("lifecycle", f"{b['code']} auto-archived (closed 30+ days)", "info", b["code"])
                        save_profile(b)
                        archived.append(b["code"])
                except (ValueError, IndexError):
                    pass
        elif lc == "active":
            # R6：classified 壳不 auto-pause——涉密标采购周期天然长、低频更新是常态，
            # 90 天无 sync 会把在跑壳悄悄暂停出 active 视图（镜子失真）。
            if b.get("kind") == "classified" or b.get("classified"):
                continue
            last_sync = b.get("last_sync", "")
            if last_sync:
                try:
                    d = datetime.strptime(last_sync.split()[0], "%Y-%m-%d").date()
                    if (today - d).days >= 90:
                        b["lifecycle"] = "paused"
                        b["pause_reason"] = "auto: 90 天无活动"
                        b["paused_at"] = _now()
                        b["updated_at"] = b["paused_at"]
                        notify.log_module("lifecycle", f"{b['code']} auto-paused (90+ days inactive)", "warn", b["code"])
                        save_profile(b)
                        paused.append(b["code"])
                except (ValueError, IndexError):
                    pass
    if archived or paused:
        notify.log_sys(f"自动归档 {len(archived)} 个 · 自动暂停 {len(paused)} 个", "info")
    return archived, paused


def delete(code):
    """删除标（profile + truth bids）。"""
    ok = truth.delete_bid(code)
    if ok:
        notify.sse.broadcast("bid_deleted", {"code": code})
    return ok


_LTC_NEXT = {
    "L1": {"skill": "lead_capture", "label": "标讯抓取", "icon": "📡"},
    "L2": {"skill": "qualify", "label": "资质评分", "icon": "🎯"},
    "L3": {"playbook": "pb-seal", "label": "封标流水线", "icon": "📦"},
    "L4": {"skill": "delivery_extract", "label": "合同抽取", "icon": "📄"},
    "L5": {"skill": "archive_close", "label": "归档", "icon": "📦"},
}

# next_actions 表读取缓存（5s TTL——all_bids 逐标 _enrich，避免 N 次查询）
_NA_CACHE = {"ts": 0.0, "data": {}}


def _next_actions() -> dict:
    import time as _time
    if _time.time() - _NA_CACHE["ts"] > 5:
        from ..store import app_db
        try:
            _NA_CACHE["data"] = app_db.list_next_actions()
        except Exception:
            _NA_CACHE["data"] = {}
        _NA_CACHE["ts"] = _time.time()
    return _NA_CACHE["data"]


def invalidate_next_actions_cache() -> None:
    """next_actions 同步后立即失效缓存（下次读即时生效）。"""
    _NA_CACHE["ts"] = 0.0


def _enrich(b, status="active"):
    """给 bid 补生命周期与业务默认字段（幂等）。"""
    now = _now()
    if "lifecycle" not in b:
        b["lifecycle"] = status
        b["created_at"] = now
        b["updated_at"] = now
    b.setdefault("tier", "未分级")
    b.setdefault("priority", "P2")
    b.setdefault("due_at", "")
    b.setdefault("last_sync", b.get("updated_at", ""))
    b.setdefault("industry", "未分类")
    b.setdefault("region", "未分类")
    b.setdefault("competitors", [])
    b.setdefault("est_amount", 0)
    b.setdefault("decision_maker", "")
    b.setdefault("partners", [])
    b.setdefault("loss_reason", "")
    b.setdefault("ltc_stage", "bid")
    b.setdefault("ai_summaries", "[]")
    b.setdefault("lifecycle_history", "[]")
    # next_action：zcode 智能建议（next_actions 表）优先，无则回退 ltc_stage 静态映射
    code = b.get("code", "")
    zcode_na = _next_actions().get(code)
    if zcode_na:
        na = {"label": zcode_na.get("label", ""), "icon": zcode_na.get("icon", "") or "▶",
              "reason": zcode_na.get("reason", ""), "source": "zcode"}
        if zcode_na.get("skill"):
            na["skill"] = zcode_na["skill"]
        if zcode_na.get("playbook"):
            na["playbook"] = zcode_na["playbook"]
        b["next_action"] = na
    else:
        ltc = b.get("ltc_stage", "bid")
        b["next_action"] = _LTC_NEXT.get(ltc, {"label": "—", "icon": "✓"})
    return b


def gen_auto_code():
    return f"BB-AUTO-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
