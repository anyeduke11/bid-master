#!/usr/bin/env python3
"""verify_audit.py · auditor 机检复核（"谁审查审查者" · acceptance §3.5）

两类机械检查（不依赖 LLM，补位模型稳定性波动）：
  A. cite 逐字存在率：审计缺陷里每条 cite.quote 必须逐字存在于被审文件 → 100%（否则 auditor 引用造假）
  2. 响应引文一致性：草稿"评分点响应"中的引文，必须与规格单 requirement 逐字一致
     （抓『引文截断/改写』——LLM 审查易漏，机检必中）

用法：
  python3 rules/verify_audit.py --bid <bid_id> --round N [--source <被审文件路径>]... [--json]
  说明：--source 为被审文件；缺省自动取 draft/ch-*.md。
退出码：0 通过；1 存在机检违规。
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

DATA_ROOT = Path.home() / ".bidmaster"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def check(bid_id: str, rnd: int, sources: list) -> dict:
    ws = DATA_ROOT / "bids" / bid_id
    audit_p = ws / "audit" / f"audit-r{rnd}.json"
    if not audit_p.exists():
        return {"pass": False, "errors": [f"缺审计报告 {audit_p}"],
                "error_items": [{"class": "missing_report", "message": f"缺审计报告 {audit_p}"}]}
    rep = json.loads(audit_p.read_text(encoding="utf-8"))
    src_text = "\n".join(_read(Path(s)) for s in sources if Path(s).exists())
    flat = re.sub(r"\s+", "", src_text)
    errors, error_items, checks = [], [], []

    # A. cite.quote 逐字存在于被审文件
    n_cite = n_cite_ok = 0
    for f in rep.get("findings") or []:
        q = re.sub(r"\s+", "", str((f.get("cite") or {}).get("quote", "")))
        if not q:
            continue
        n_cite += 1
        if q in flat:
            n_cite_ok += 1
        else:
            msg = f"cite 不存在于被审文件：[{f.get('where','?')}] {q[:40]}"
            errors.append(msg)
            error_items.append({"class": "cite_missing", "message": msg})
    checks.append({"name": "cite_verbatim", "ok": n_cite == n_cite_ok,
                   "detail": f"{n_cite_ok}/{n_cite} 逐字命中（要求 100%）"})

    # B. 响应引文 vs 规格 requirement 逐字一致（抓截断/改写）
    spec_p = ws / "data" / "spec.json"
    n_req = n_req_ok = 0
    if spec_p.exists():
        spec = json.loads(spec_p.read_text(encoding="utf-8"))
        drafts = "\n".join(_read(Path(s)) for s in sources if Path(s).exists())
        dflat = re.sub(r"\s+", "", drafts)
        for pt in spec.get("scoring_points") or []:
            req = str(pt.get("requirement", "")).strip()
            if len(req) < 8:
                continue
            n_req += 1
            if re.sub(r"\s+", "", req) in dflat:
                n_req_ok += 1
            else:
                msg = f"评分点 {pt.get('id')} 的招标要求引文在草稿中不逐字（截断/改写）：{req[:40]}"
                errors.append(msg)
                error_items.append({"class": "scoring_point", "sp_id": str(pt.get("id", "")), "message": msg})
        checks.append({"name": "requirement_verbatim", "ok": n_req == n_req_ok,
                       "detail": f"{n_req_ok}/{n_req} requirement 逐字一致"})
    # DEV-0052：error_items 结构化分类（cite_missing→auditor / scoring_point→writer），
    # 工作流路由不再依赖错误文案字符串前缀（文案措辞变更不再静默破坏路由）
    return {"pass": not errors, "checks": checks, "errors": errors, "error_items": error_items,
            "round": rnd, "audit_report": str(audit_p)}


def main() -> int:
    ap = argparse.ArgumentParser(description="auditor 机检复核（cite 逐字 + 引文一致性）")
    ap.add_argument("--bid", required=True)
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--source", action="append", default=[], help="被审文件（可多次）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    ws = DATA_ROOT / "bids" / a.bid
    sources = a.source or [str(p) for p in sorted((ws / "draft").glob("*.md"))]
    if not sources:
        print("❌ 无被审文件（--source 或 draft/*.md）")
        return 3
    rep = check(a.bid, a.round, sources)
    out_p = ws / "verify" / f"verify_audit_r{a.round}.json"
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps({**rep, "status": "registered", "producer": "verify_audit",
                                 "ts": datetime.now().astimezone().isoformat(timespec="seconds")},
                                ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # P1-2 登记制：机检报告落库（registered；final 由门禁提升）
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import store
        store.init()
        store.register_artifact(a.bid, "verify_audit", str(out_p), status="registered", producer="verify_audit")
    except Exception:
        pass
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(f"{'✅ PASS' if rep['pass'] else '⛔ FAIL'} {a.bid} round-{a.round} → {out_p.name}")
        for e in rep["errors"]:
            print("  -", e)
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
