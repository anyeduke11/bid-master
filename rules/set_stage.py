#!/usr/bin/env python3
"""set_stage.py · 生命周期状态机 S0–S9 唯一写入口（W2 2.1）

设计依据：docs/baw-design-v3.md §8（状态机与门禁矩阵）/§10（强制机制）
────────────────────────────────────────────────────────────────
单一写者：~/.bidmaster/memory/bids.jsonl 的 stage 字段只有本脚本写。
看板按钮（bid.advance_stage）/ CLI / ZCode 会话触发的都是同一校验——
看板只是按门铃的 UI，权限不比命令行大。

状态机：S0 线索 → S1 预审 → S2 决策 → S3 解构 → S4 编制 → S5 审查
        → S6 封标 → S7 开标 → S8 结果 → S9 归档（只前进，逐级推进）

门禁矩阵（§8.2，工作区 = ~/.bidmaster/bids/<bid_id>/）：
  S2→S3  data/stage0.json 含 lessons_applied，且每个教训 ID 存在于 memory/lessons.md
  S3→S4  data/hits_recon.json 关键词对账 100%（每条命中/排除均带理由）
  S4→S5  data/completeness.json = PASS + 规格单评分点全覆盖 + 素材匹配率 ≥ 80%
  S5→S6  最新轮 audit 阻断级=0 + locator hit_rate ≥ 95% + --sign-off（L3 人工签核）
  S8→S9  archive/proposal.json status=confirmed（人工采纳）+ 脱敏机检 0 命中
  其余迁移无门禁，照常记录。
  kind=classified（涉密壳，R1）：全部转移门禁全豁——壳无内容产物，五道内容门禁无物可检；
  每次推进 extra.gate_exempt=true 留痕（gate_attempts 照落）。壳唯一建档入口 = bid.create
  （bootstrap 拒绝 classified，保证 bid_profile 必建、镜子有死线可扫）。

用法：
  python3 rules/set_stage.py --bid <bid_id> --to S4 [--sign-off Duke] [--json] [--timing]
  python3 rules/set_stage.py --bid <bid_id> --to S5 --ignore-material "ch-G 人员证书待人事补齐，先行推进审查"   # S4→S5 素材率门禁可选忽略（DEV-0056）
  python3 rules/set_stage.py --bid <bid_id> --settle-material   # 材料补齐后复验销单（素材债工单 done）
  python3 rules/set_stage.py --bid <bid_id> --bootstrap S3   # 仅为存量大标建基线（不走过门禁，一次性）
  python3 rules/set_stage.py --bid <bid_id> --show

退出码：0 放行/推进成功；2 门禁拦截（输出卡点清单）；3 用法错误
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# DEV-0042：数据根可经 BIDMASTER_HOME 环境变量覆盖（与 rules/store.py 同一变量；测试密封用）
DATA_ROOT = Path(os.environ.get("BIDMASTER_HOME") or (Path.home() / ".bidmaster"))
BIDS_JSONL = DATA_ROOT / "memory" / "bids.jsonl"
LESSONS_MD = DATA_ROOT / "memory" / "lessons.md"
AUDIT_LOG = DATA_ROOT / "log" / "set_stage.log.jsonl"
STAGES = [f"S{i}" for i in range(10)]
MIN_MATERIAL_MATCH = 0.80
MIN_HIT_RATE = 0.95


# ────────────────────────── 工具 ──────────────────────────
def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return "sha256:" + h.hexdigest()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _load_bids() -> list:
    """真实层读口（v0.5.0）：truth.db 权威；store 初始化时自动从 jsonl 单向导入。"""
    import store as _store
    _store.init()
    return _store.load_normalized()


def _save_bids(records: list) -> None:
    """v0.5.0 起禁止直写 jsonl——真实层唯一写口为 rules/store.py。保留签名仅为兼容旧调用报警。"""
    raise RuntimeError("jsonl 直写已废弃：状态写请走 rules/store.py（真实层唯一写口）")


def _store():
    import store as _s
    _s.init()
    return _s


def _audit(event: dict) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    prev = AUDIT_LOG.read_text(encoding="utf-8") if AUDIT_LOG.exists() else ""
    AUDIT_LOG.write_text(prev + json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")


# ────────────────────────── 门禁（§8.2） ──────────────────────────
def gate_s2_s3(ws: Path, ctx: dict):
    """阶段 0 产物含 lessons_applied，且引用有效教训 ID（P3'-2 起读 lessons 表权威层）。"""
    blockers = []
    p = ws / "data" / "stage0.json"
    if not p.exists():
        return False, [f"缺阶段 0 产物 {p}（需含 lessons_applied 字段）"], {}
    d = _read_json(p)
    applied = d.get("lessons_applied") or []
    if not applied:
        return False, ["stage0.json 的 lessons_applied 为空：开工必读 lessons 并引用有效教训 ID（运行协议）"], {}
    s = _store()
    s.import_lessons_from_md()          # md → 表 一次性兜底导入（幂等）
    for lid in applied:
        if not re.fullmatch(r"L-\d+", str(lid)):
            blockers.append(f"教训 ID 格式非法：{lid!r}（应为 L-<数字>）")
        elif not s.lesson_exists(str(lid)):
            blockers.append(f"lessons_applied 引用了不存在的教训：{lid}（lessons 表无此 ID）")
    return (not blockers), blockers, {"lessons_valid": len(applied) - len([b for b in blockers if "教训" in b])}


def gate_s3_s4(ws: Path, ctx: dict):
    """hits 关键词对账 100% PASS：每条命中/排除均带理由。"""
    blockers = []
    p = ws / "data" / "hits_recon.json"
    if not p.exists():
        return False, [f"缺关键词对账 {p}（schema：{{items:[{{keyword,status:收录|排除,reason}}]}}）"], {}
    d = _read_json(p)
    items = d.get("items") or []
    if not items:
        return False, ["hits_recon.json 无 items：关键词对账为空"], {}
    for i, it in enumerate(items, 1):
        kw = (it.get("keyword") or "").strip()
        st = (it.get("status") or "").strip()
        reason = (it.get("reason") or "").strip()
        if not kw:
            blockers.append(f"第 {i} 条缺 keyword")
        if st not in ("收录", "排除"):
            blockers.append(f"关键词「{kw}」status 非法：{st!r}（只允许 收录/排除）")
        if not reason:
            blockers.append(f"关键词「{kw}」缺收录/排除理由（对账要求逐条覆盖）")
    n_ok = sum(1 for it in items if (it.get("status") in ("收录", "排除")) and (it.get("reason") or "").strip())
    rate = n_ok / len(items) if items else 0
    if not blockers and rate < 1.0:
        blockers.append(f"对账覆盖率 {rate:.0%} < 100%")
    return (not blockers), blockers, {"coverage": rate, "total": len(items)}


def gate_s4_s5(ws: Path, ctx: dict):
    """完整性核验 PASS + 规格单评分点全覆盖 + 评分点-素材匹配率 ≥ 80% + verify_draft 机检全过（v0.5.0 接线）。

    DEV-0056：素材率一道改为**可选忽略**（--ignore-material "<原因>"）——owner 明示原因后放行，
    其余检查（完整性 PASS / 章节映射 / verify_draft 机检）不豁免；忽略时登记材料债工单，
    补料后 --settle-material 复验销单。忽略行为进 stage_history extra 审计留痕。
    """
    blockers = []
    comp = ws / "data" / "completeness.json"
    spec = ws / "data" / "spec.json"
    if not comp.exists():
        return False, [f"缺完整性核验 {comp}（{{result: PASS|FAIL, checks:[…]}}）"], {}
    if _read_json(comp).get("result") != "PASS":
        return False, ["完整性核验未 PASS（见 completeness.json 的 checks 明细）"], {}
    if not spec.exists():
        return False, [f"缺写作规格单 {spec}（{{scoring_points:[{{id,chapter,material_ptrs}}]}}）"], {}
    spec_d = _read_json(spec)
    pts = spec_d.get("scoring_points") or []
    if not pts:
        return False, ["规格单无 scoring_points：评分点全覆盖无从谈起"], {}
    no_chapter = [pt.get("id") for pt in pts if not (pt.get("chapter") or "").strip()]
    if no_chapter:
        blockers.append(f"评分点未映射章节（全覆盖缺口）：{no_chapter}")
    with_material = sum(1 for pt in pts if pt.get("material_ptrs"))
    rate = with_material / len(pts)
    ignore_reason = (ctx.get("ignore_material") or "").strip()
    if rate < MIN_MATERIAL_MATCH and not ignore_reason:
        blockers.append(f"评分点-素材匹配率 {rate:.0%} < {MIN_MATERIAL_MATCH:.0%}（{with_material}/{len(pts)}）")
    # P1-2 机检接线（读登记表）：全部章节 verify_draft 登记存在且 pass（registered/final 均可，指纹须未变）
    chapters = sorted({pt.get("chapter") for pt in pts if pt.get("chapter")})
    import store as _st
    _st.init()
    reg = [r for r in _st.list_artifacts(ws.name, "verify_draft")]
    checked = 0
    for ch in chapters:
        cand = [r for r in reg if f"verify_draft_{ch}.json" in r["path"]]
        if not cand:
            blockers.append(f"机检未跑：{ch} 无 verify_draft 登记（rules/verify_draft.py --chapter {ch}）")
            continue
        r = max(cand, key=lambda x: x["id"])
        p = Path(r["path"])
        if not p.exists():
            blockers.append(f"机检报告文件缺失：{p}")
            continue
        fp_now = "sha256:" + __import__("hashlib").sha256(p.read_bytes()).hexdigest()
        if fp_now != r["fingerprint"]:
            blockers.append(f"机检报告被改动（指纹不符）：{p}")
            continue
        v = _read_json(p)
        if v.get("pass") is not True:
            blockers.append(f"机检未过：{ch}（verify_draft blockers：{v.get('blockers') or '见报告'}）")
        else:
            checked += 1
    extra = {"material_match_rate": rate, "points": len(pts), "verify_draft_checked": checked}
    if ignore_reason:
        extra["material_gate"] = "ignored"
        extra["ignore_reason"] = ignore_reason
    return (not blockers), blockers, extra


def material_debt(bid_id: str) -> dict:
    """素材债盘点：缺 material_ptrs 的评分点清单（--settle-material 与工单留痕共用）。"""
    spec = DATA_ROOT / "bids" / bid_id / "data" / "spec.json"
    if not spec.exists():
        return {"ok": False, "error": f"缺写作规格单 {spec}"}
    pts = _read_json(spec).get("scoring_points") or []
    missing = [{"id": pt.get("id"), "chapter": pt.get("chapter")} for pt in pts if not (pt.get("material_ptrs") or [])]
    rate = (len(pts) - len(missing)) / len(pts) if pts else 0.0
    return {"ok": True, "rate": rate, "points": len(pts), "missing": missing,
            "threshold": MIN_MATERIAL_MATCH}


def gate_s5_s6(ws: Path, ctx: dict):
    """最新轮 audit 阻断级=0 + locator hit_rate ≥95%（samples 复算）+ verify_audit 机检 pass + 人工签核（L3）。"""
    blockers = []
    audit_dir = ws / "audit"
    rounds = sorted(audit_dir.glob("audit-r*.json")) if audit_dir.exists() else []
    if not rounds:
        return False, ["无审计记录（audit/audit-r<N>.json）：S5→S6 须先过 auditor 至少一轮"], {}
    latest_no = max(int(r.stem.split("r")[-1]) for r in rounds)
    latest = _read_json(rounds[-1])
    blockings = [f for f in (latest.get("findings") or []) if f.get("severity") == "阻断"]
    if blockings:
        for b in blockings:
            cite = (b.get("cite") or {}).get("quote", "")
            blockers.append(f"审计阻断级缺陷未清：{b.get('where', '?')}「{cite[:40]}」{b.get('note', '')}")
    # P1-3：locator 复算（读登记表 samples），废自报数字
    import store as _st
    _st.init()
    loc_rows = [r for r in _st.list_artifacts(ws.name, "locator") if "locator-report" in r["path"]]
    if not loc_rows:
        blockers.append("缺定位抽查登记（locator-report，samples schema v2）")
    else:
        row = max(loc_rows, key=lambda x: x["id"])
        loc = Path(row["path"])
        if not loc.exists():
            blockers.append(f"locator 报告文件缺失：{loc}")
        else:
            ld = _read_json(loc)
            samples = ld.get("samples")
            if not isinstance(samples, list) or not samples:
                blockers.append("locator-report 缺 samples 列表（schema v2：门禁复算 hit_rate，自报数字不再采信）")
            else:
                # DEV-0081：hit_rate 复算收进 else 分支——原先 samples 缺失时 rate 未绑定即引用，
                # 门禁以 UnboundLocalError 崩溃而非返回卡点清单
                hits = sum(1 for s in samples if s.get("hit") is True)
                rate = hits / len(samples)
                if abs(float(ld.get("hit_rate", -1)) - rate) > 1e-9:
                    blockers.append(f"locator 自报 hit_rate={ld.get('hit_rate')} 与复算 {rate:.2%} 不符（以复算为准）")
                if rate < MIN_HIT_RATE:
                    blockers.append(f"locator 复算 hit_rate {rate:.2%} < {MIN_HIT_RATE:.0%}，S5→S6 阻断")
    # P1-2 机检接线：最新轮 verify_audit 报告存在且 pass
    va = ws / "verify" / f"verify_audit_r{latest_no}.json"
    if not va.exists():
        blockers.append(f"机检未跑：缺 {va}（rules/verify_audit.py --round {latest_no}）")
    elif _read_json(va).get("pass") is not True:
        blockers.append(f"机检未过：verify_audit r{latest_no}（cite/引文一致性，见报告）")
    # P1-2 机检接线（读登记表）：最新轮 verify_audit 登记存在且 pass
    va_rows = [r for r in _st.list_artifacts(ws.name, "verify_audit") if f"r{latest_no}" in r["path"]]
    if not va_rows:
        blockers.append(f"机检未跑：verify_audit r{latest_no} 无登记（rules/verify_audit.py --round {latest_no}）")
    else:
        vrow = max(va_rows, key=lambda x: x["id"])
        vp = Path(vrow["path"])
        if not vp.exists():
            blockers.append(f"verify_audit 报告文件缺失：{vp}")
        else:
            v = _read_json(vp)
            if v.get("pass") is not True:
                blockers.append(f"机检未过：verify_audit r{latest_no}（cite/引文一致性，见报告）")
    if not (ctx.get("sign_off") or "").strip():
        blockers.append("缺人工放行签核：须以 --sign-off <姓名> 显式通过（L3 审批位，不可代签）")
    return (not blockers), blockers, {"audit_round": rounds[-1].name, "blocking": len(blockings)}


def gate_s8_s9(ws: Path, ctx: dict):
    """apply_archive 前置：proposal 已人工采纳（confirmed）+ 脱敏机检 0 命中 + lessons supersession 完整。"""
    blockers = []
    prop = ws / "archive" / "proposal.json"
    if not prop.exists():
        return False, [f"缺归档提案 {prop}（由 bid-archivist 产出、人工确认后 status=confirmed）"], {}
    d = _read_json(prop)
    if d.get("status") != "confirmed":
        blockers.append(f"proposal.json status={d.get('status')!r}：须经人工采纳（confirmed）方可归档（飞轮强制，不靠自觉）")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import desensitize as _ds
    hits = _ds.scan_text(prop.read_text(encoding="utf-8"))
    if hits:
        blockers.append(f"归档提案脱敏机检命中 {len(hits)} 处（L3 红线，见 desensitize 报告）：先脱敏再归档")
    for i, les in enumerate(d.get("lessons") or [], 1):
        if "supersession" not in les:
            blockers.append(f"第 {i} 条教训缺 supersession 字段（须写明取代的旧教训 ID 或'无'）")
    return (not blockers), blockers, {"desens_hits": len(hits)}


GATES = {
    ("S2", "S3"): gate_s2_s3,
    ("S3", "S4"): gate_s3_s4,
    ("S4", "S5"): gate_s4_s5,
    ("S5", "S6"): gate_s5_s6,
    ("S8", "S9"): gate_s8_s9,
}

# R1（工程审查 2026-09-19）：classified 壳单门禁豁免表——显式单点。
# 空表 = 全部 10 个转移豁免（壳无招标文件/章节/审计产物，五道内容门禁无物可检）。
# 未来若需对壳保留某道轻门（如 S8→S9 复盘门），在此登记即可，advance_payload 无需再改。
CLASSIFIED_GATES: dict = {}


# ────────────────────────── 主流程 ──────────────────────────
def advance_payload(bid_id: str, to_stage: str, sign_off: str = "", ignore_material: str = ""):
    """进程内推进接口：返回 (rc, payload)。看板 bid.advance_stage / 未来 ingest 复用；
    CLI 的 advance() 是它的打印包装。rc：0 放行/成功，2 门禁拦截或非法迁移，3 用法错误。"""
    records = _load_bids()
    rec = next((r for r in records if r.get("bid_id") == bid_id), None)
    if rec is None:
        return 2, {"ok": False, "blockers": [f"bid 不存在：{bid_id}（看板 bid.create 或 --bootstrap 建基线）"]}
    cur = rec.get("stage", "S0")
    if to_stage == cur:
        return 0, {"ok": True, "bid_id": bid_id, "stage": cur, "note": "no-op（已在该阶段）"}
    if STAGES.index(to_stage) < STAGES.index(cur):
        return 2, {"ok": False, "blockers": [f"状态只前进：当前 {cur}，拒绝回退到 {to_stage}（如需纠错走人工数据修复并留痕）"]}
    if STAGES.index(to_stage) - STAGES.index(cur) != 1:
        return 2, {"ok": False, "blockers": [f"逐级推进：{cur} → {to_stage} 跳级被拒绝（一次只推一级）"]}
    if ignore_material.strip() and (cur, to_stage) != ("S4", "S5"):
        return 3, {"ok": False, "blockers": ["--ignore-material 仅适用于 S4→S5 素材门禁"]}

    t0 = time.perf_counter()
    gate = GATES.get((cur, to_stage))
    if gate is not None and rec.get("kind") == "classified" and gate not in CLASSIFIED_GATES:
        # R1：涉密壳门禁全豁（单点分支，豁免语义见 CLASSIFIED_GATES 注释）
        ok, blockers, extra = True, [], {"gate_exempt": True, "exempt": f"{cur}→{to_stage}", "note": "classified 壳：内容门禁无物可检"}
    elif gate is None:
        ok, blockers, extra = True, [], {"note": "本迁移无门禁"}
    else:
        ok, blockers, extra = gate(DATA_ROOT / "bids" / bid_id,
                                   {"sign_off": sign_off, "ignore_material": ignore_material})
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    event = {"ts": _now(), "bid_id": bid_id, "from": cur, "to": to_stage,
             "ok": ok, "blockers": blockers, "gate_ms": elapsed_ms, "sign_off": sign_off or None,
             "extra": extra, "producer": "set-stage"}
    _audit(event)
    # P1-3：门禁尝试结构化落库 + epoch 递增（一致性协议 L2 的变更信号源）
    # DEV-0042 修复：原先连续两次调用 record_gate_attempt（复制残留），同一迁移插两行
    # gate_attempts 且 epoch 双 bump——读方看到跳变。收敛为一次。
    s = _store()
    s.record_gate_attempt(bid_id, cur, to_stage, ok, blockers, elapsed_ms, sign_off or None)

    if not ok:
        # DEV-0041 可监测性：门禁拦截自动生成 Now 待办工单（通过时自动销单）
        try:
            _store().upsert_ticket(f"TIK-gate-{bid_id}-{to_stage}", "gate", "generated", bid_id)
        except Exception:
            pass
        return 2, {"ok": False, "bid_id": bid_id, "from": cur, "to": to_stage,
                   "gate_ms": elapsed_ms, "blockers": blockers, "extra": extra}

    # v0.5.0：真实层唯一写口（truth.db 事务 + busy_timeout，jsonl 由 store 兼容导出）
    _store().set_stage(bid_id, to_stage, cur, sign_off or None, elapsed_ms)
    # DEV-0041：门禁通过 → 销掉对应拦截工单
    try:
        _store().upsert_ticket(f"TIK-gate-{bid_id}-{to_stage}", "gate", "done", bid_id)
    except Exception:
        pass
    # DEV-0056：素材门禁被忽略放行 → 登记材料债工单 + 落盘缺口清单（补料后 --settle-material 销单）
    # R1：classified 壳无素材门禁可言，不产材料债（防 --ignore-material 误传时给壳开假工单）
    if cur == "S4" and to_stage == "S5" and ignore_material.strip() and rec.get("kind") != "classified":
        try:
            debt = material_debt(bid_id)
            debt.update({"ignored_reason": ignore_material.strip(),
                         "created_at": _now(), "status": "open"})
            debt_p = DATA_ROOT / "bids" / bid_id / "data" / "material_debt.json"
            debt_p.write_text(json.dumps(debt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            _store().upsert_ticket(f"TIK-material-{bid_id}", "material", "generated", bid_id)
            # DEV-0057：登记制纪律——落盘即登记（reconcile 会抓未登记产物）
            _store().register_artifact(bid_id, "material_debt", str(debt_p), producer="set-stage")
        except Exception:
            pass
    # P1-2 状态机：门禁通过后把已登记的机检报告提升为 final（生产者不得自报 final）
    _PROMOTE = {"S4": ("verify_draft",), "S5": ("verify_audit", "locator"), "S6": ("audit",)}
    try:
        for k in _PROMOTE.get(cur, ()):
            for row in _store().list_artifacts(bid_id, k):
                if row["status"] == "registered":
                    _store().promote_artifact(bid_id, k, row["path"])
    except Exception:
        pass
    return 0, {"ok": True, "bid_id": bid_id, "from": cur, "to": to_stage,
               "gate_ms": elapsed_ms, "extra": extra}


def advance(bid_id: str, to_stage: str, sign_off: str, as_json: bool, timing: bool, ignore_material: str = "") -> int:
    rc, out = advance_payload(bid_id, to_stage, sign_off, ignore_material)
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif out.get("ok") and "blockers" not in out:
        if out.get("note"):
            print(f"{bid_id} 已在 {out.get('stage')}，no-op")
        else:
            print(f"✅ {bid_id}: {out['from']} → {out['to']}（门禁通过，校验耗时 {out['gate_ms']}ms）{json.dumps(out.get('extra', {}), ensure_ascii=False)}")
    else:
        print(f"⛔ 门禁拦截 {out.get('from')} → {out.get('to')}（校验耗时 {out.get('gate_ms', 0)}ms）。卡点清单：")
        for i, b in enumerate(out.get("blockers", []), 1):
            print(f"  {i}. {b}")
    if timing and "gate_ms" in out:
        print(f"[timing] gate_ms={out['gate_ms']} 读写文件数=2（bids.jsonl + 门禁产物）", file=sys.stderr)
    return rc


def settle_material(bid_id: str) -> int:
    """材料补齐后的复验销单：素材率 ≥ 阈值 → 材料债工单 done；否则列出缺口退出 1。"""
    debt = material_debt(bid_id)
    if not debt.get("ok"):
        print(f"⛔ {debt.get('error')}")
        return 2
    rate, missing = debt["rate"], debt["missing"]
    tid = f"TIK-material-{bid_id}"
    if rate >= debt["threshold"] and not missing:
        _store().upsert_ticket(tid, "material", "done", bid_id)
        dp = DATA_ROOT / "bids" / bid_id / "data" / "material_debt.json"
        if dp.exists():
            d = _read_json(dp)
            d.update({"status": "settled", "settled_at": _now()})
            dp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"✅ {bid_id} 素材债已清：匹配率 {rate:.0%} ≥ {debt['threshold']:.0%}，工单 {tid} → done")
        return 0
    print(f"⛔ 素材债未清：匹配率 {rate:.0%} < {debt['threshold']:.0%}，缺 material_ptrs 的评分点：")
    for m in missing:
        print(f"  - {m.get('id')}（{m.get('chapter')}）")
    print("补料路径：编辑 data/spec.json 给对应评分点加 material_ptrs（kb 指针），再重跑 --settle-material")
    return 1


def bootstrap(bid_id: str, stage: str) -> int:
    records = _load_bids()
    if any(r.get("bid_id") == bid_id for r in records):
        print(f"bid 已存在：{bid_id}，拒绝重复 bootstrap")
        return 3
    # v0.5.0：真实层建档（owner 逃生舱——非门禁通道，全程审计留痕；kind 自动判定走 store.kind_for）
    # R1：bootstrap 不提供 kind 入参——classified 壳唯一建档入口 = bid.create（保证 bid_profile 必建），
    # 结构性拒绝，无 CLI/程序路径可经 bootstrap 造壳。
    s = _store()
    kind = s.kind_for(bid_id)
    s.create_bid(bid_id, stage, bootstrapped=True,
                 note="owner 逃生舱（非门禁通道，审计留痕）", kind=kind)
    _audit({"ts": _now(), "bid_id": bid_id, "action": "bootstrap", "stage": stage, "kind": kind, "producer": "set-stage"})
    print(f"✅ 已建基线：{bid_id} @ {stage}（bootstrapped, kind={kind}）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="S0–S9 状态机唯一写入口（门禁内嵌）")
    ap.add_argument("--bid", required=True)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--to", choices=STAGES, help="目标阶段（逐级推进）")
    g.add_argument("--bootstrap", choices=STAGES, help="存量大标建基线（仅当 bid 不存在）")
    g.add_argument("--show", action="store_true")
    g.add_argument("--settle-material", action="store_true",
                   help="材料补齐后复验：素材率达标 → 材料债工单销单（DEV-0056）")
    ap.add_argument("--sign-off", default="", help="L3 人工签核姓名（S5→S6 必填）")
    ap.add_argument("--ignore-material", default="",
                    help='忽略 S4→S5 素材率门禁放行，必须写明原因（登记材料债工单，补料后 --settle-material 销单）')
    ap.add_argument("--json", action="store_true", help="机器可读输出（看板 bid.advance_stage 调此格式）")
    ap.add_argument("--timing", action="store_true")
    a = ap.parse_args()

    if not (a.to or a.bootstrap or a.show or a.settle_material):
        ap.error("需要 --to / --bootstrap / --show / --settle-material 之一")

    if a.show:
        rec = next((r for r in _load_bids() if r.get("bid_id") == a.bid), None)
        print(json.dumps(rec, ensure_ascii=False, indent=2) if rec else f"bid 不存在：{a.bid}")
        return 0
    if a.bootstrap:
        return bootstrap(a.bid, a.bootstrap)
    if a.settle_material:
        return settle_material(a.bid)
    return advance(a.bid, a.to, a.sign_off, a.json, a.timing, a.ignore_material)


if __name__ == "__main__":
    sys.exit(main())
