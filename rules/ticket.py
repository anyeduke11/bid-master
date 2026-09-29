#!/usr/bin/env python3
"""ticket.py · 提示词工单机制（W3 3.3）

设计依据：docs/baw-design-v3.md §11（提示词工单）、PRD v6 §7
────────────────────────────────────────────────────────────────
流转：看板/CLI generate → queue/<ticket_id>.json（status=generated，给人复制也可给 CronCreate 批处理）
      → ZCode 会话执行（产物 run manifest 回填 ticket_id → status=executed，由执行方写）
      → reconcile（本脚本对账：产物 ticket_id 匹配 → status=consumed）

纪律（design §11）：工单给路径和目标，不内嵌大段内容；完成条件=门禁清单原文；
模板进 Git 走提案流。模板即"改模板=改生产指令"，与 agent/skill 同受 golden 回归约束。

用法：
  python3 rules/ticket.py generate --template audit-round --bid <bid_id> [--round 1] [--stage S5]
  python3 rules/ticket.py list [--status generated|executed|consumed]
  python3 rules/ticket.py reconcile
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TPL_DIR = REPO / "rules" / "tickets"
QUEUE = Path(os.environ.get("BIDMASTER_HOME") or (Path.home() / ".bidmaster")) / "queue"
DATA_ROOT = Path(os.environ.get("BIDMASTER_HOME") or (Path.home() / ".bidmaster"))


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_tpl(name: str) -> dict:
    p = TPL_DIR / f"{name}.json"
    if not p.exists():
        raise SystemExit(f"模板不存在：{p}（可用：{sorted(x.stem for x in TPL_DIR.glob('*.json'))}）")
    return json.loads(p.read_text(encoding="utf-8"))


def _bid_record(bid_id: str) -> dict:
    # DEV-0042：真实层权威读（truth.db）。jsonl 兼容导出已退役，原直读 bids.jsonl 会漏掉
    # 看板/命令通道新建的标（实测 ticket.generate 报"bid 不存在"）。
    try:
        import store as _store
        _store.init()
        rec = _store.get_bid(bid_id)
        if rec:
            return rec
    except Exception:
        pass
    p = DATA_ROOT / "memory" / "bids.jsonl"
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                if r.get("bid_id") == bid_id:
                    return r
    raise SystemExit(f"bid 不存在：{bid_id}")


def create_ticket(template: str, bid_id: str, round_no: int, stage: str) -> dict:
    """构建工单并写 queue 文件（真实层 tickets 表登记）。返回 ticket dict。"""
    tpl = _load_tpl(template)
    rec = _bid_record(bid_id) if bid_id else {}
    cur_stage = rec.get("stage", stage or "S0")
    tid = re.sub(r"[^A-Za-z0-9_\-]", "",
                 f"TIK-{template}-{bid_id or 'general'}-{int(datetime.now().timestamp())}")[:80]
    ws = DATA_ROOT / "bids" / bid_id if bid_id else None
    vars_ = {
        "ticket_id": tid, "bid_id": bid_id or "", "stage": stage or cur_stage,
        "round": round_no, "created_at": _now(), "workspace": str(ws) if ws else "",
        "skill": tpl.get("skill", ""), "agent": tpl.get("agent", ""),
        "spec": str(ws / "data" / "spec.json") if ws else "",
        "draft_dir": str(ws / "draft") if ws else "",
        "verify_dir": str(ws / "verify") if ws else "",
        "audit_dir": str(ws / "audit") if ws else "",
        "archive_dir": str(ws / "archive") if ws else "",
        "lessons": str(DATA_ROOT / "memory" / "lessons.md"),
        "rules_audit": str(REPO / "rules" / "audit" / "audit-rules.json"),
        "golden": str(REPO / "tests" / "golden"),
    }
    goal = tpl["goal"].format(**vars_)
    done_when = [d.format(**vars_) for d in tpl["done_when"]]
    vars_["goal"] = goal
    vars_["done_when"] = "\n".join("- " + d for d in done_when)
    ticket = {
        "ticket_id": tid, "type": template, "status": "generated",
        "created_at": vars_["created_at"], "producer": "ticket.generate",
        "bid_id": bid_id or None, "stage": vars_["stage"],
        "goal": goal,
        "agent": tpl.get("agent"), "skill": tpl.get("skill"),
        "inputs": [v.format(**vars_) for v in tpl.get("inputs", [])],
        "done_when": done_when,
        "ticket_id_backfill": "产物 manifest 必须回填本 ticket_id（acceptance G2）",
        "prompt": tpl["prompt"].format(**vars_),
    }
    return ticket


def generate(template: str, bid_id: str, round_no: int, stage: str) -> int:
    ticket = create_ticket(template, bid_id, round_no, stage)
    out = QUEUE / f"{ticket['ticket_id']}.json"
    # DEV-0081：真正落盘——原先只打印"已生成"从不写文件，queue/ 目录自 9-12 起为空，
    # reconcile 的 queue 对账永远对着空目录
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ticket, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ 工单已生成：{out}")
    print("────── 复制以下内容到 ZCode 会话启动 ──────")
    print(ticket["prompt"])
    return 0


def list_tickets(status: str) -> int:
    rows = []
    for p in sorted(QUEUE.glob("*.json")) if QUEUE.exists() else []:
        d = json.loads(p.read_text(encoding="utf-8"))
        if status and d.get("status") != status:
            continue
        rows.append((d.get("ticket_id"), d.get("type"), d.get("status"), d.get("bid_id"), d.get("created_at")))
    for r in rows:
        print(" | ".join(str(x) for x in r))
    print(f"共 {len(rows)} 张工单。")
    return 0


def reconcile() -> int:
    """对账：扫描各标产物（draft manifest / verify 报告）中的 ticket_id，匹配 → status=consumed。"""
    produced = {}
    bids_dir = DATA_ROOT / "bids"
    if bids_dir.exists():
        for f in bids_dir.glob("*/draft/*.manifest.json"):
            try:
                m = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            tid = m.get("ticket_id")
            if tid:
                produced.setdefault(tid, []).append(str(f))
        for f in bids_dir.glob("*/verify/*.json"):
            try:
                m = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            tid = m.get("ticket_id")
            if tid:
                produced.setdefault(tid, []).append(str(f))
        for f in bids_dir.glob("*/audit/*.json"):
            try:
                m = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            tid = m.get("ticket_id")
            if tid:
                produced.setdefault(tid, []).append(str(f))
    n = 0
    for p in QUEUE.glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("ticket_id") in produced and d.get("status") in ("generated", "executed"):
            d["status"] = "consumed"
            d["consumed_at"] = _now()
            d["consumed_artifacts"] = produced[d["ticket_id"]]
            p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            n += 1
            # P1-7：状态同步真实层（tickets 表）
            try:
                import store as _store
                _store.init()
                _store.upsert_ticket(d["ticket_id"], d.get("type", ""), "consumed", d.get("bid_id"))
            except Exception:
                pass
    print(f"对账完成：{n} 张工单消单（executed→consumed）；已产生产物的 ticket_id：{sorted(produced) or '无'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="提示词工单：generate / list / reconcile")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--template", required=True, help="模板名（rules/tickets/<name>.json）")
    g.add_argument("--bid", default="")
    g.add_argument("--round", type=int, default=1)
    g.add_argument("--stage", default="")
    l = sub.add_parser("list")
    l.add_argument("--status", default="")
    sub.add_parser("reconcile")
    a = ap.parse_args()
    if a.cmd == "generate":
        return generate(a.template, a.bid, a.round, a.stage)
    if a.cmd == "list":
        return list_tickets(a.status)
    return reconcile()


if __name__ == "__main__":
    sys.exit(main())
