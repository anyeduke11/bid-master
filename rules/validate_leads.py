#!/usr/bin/env python3
"""validate_leads.py · bid-scout 产物转正机检（W4 4.1）

设计依据：docs/acceptance-agents.md §3.2（scout 专项验收）
────────────────────────────────────────────────────────────────
检查项：
  1. evidence 非空率 100%（纳入 + 观察两类逐条必附 quote+url）
  2. 同指纹重复 = 0（同一指纹只允许一条非「重复」记录）
  3. 排除行 100% 带原因
  4. schema 必填字段（title/source_url/fingerprint/score/recommend/producer）

输入：~/.bidmaster/leads/scored.jsonl（bid-scout 产物）；转正 = 通过后由人工 lead.promote（L3）。
用法：
  python3 rules/validate_leads.py [--file scored.jsonl] [--json]
  python3 rules/validate_leads.py --selftest
退出码：0 通过；1 存在拦截项。
"""
import argparse
import json
import re
import sys
from pathlib import Path

LEADS = Path.home() / ".bidmaster" / "leads" / "scored.jsonl"
SAMPLE = Path(__file__).resolve().parent.parent / "tests" / "sample" / "validate_leads"
REQUIRED = ("title", "source_url", "fingerprint", "score", "recommend", "producer")
RECOMMENDS = {"纳入", "观察", "排除", "重复"}


def validate(rows: list) -> dict:
    problems, stats = [], {"total": len(rows), "纳入": 0, "观察": 0, "排除": 0, "重复": 0}
    seen_fp = {}
    for i, r in enumerate(rows, 1):
        bid = f"第{i}条({str(r.get('title'))[:20]})"
        lacking = [k for k in REQUIRED if r.get(k) in (None, "")]
        if lacking:
            problems.append(f"{bid} 缺必填字段 {lacking}")
        rec = r.get("recommend")
        if rec not in RECOMMENDS:
            problems.append(f"{bid} recommend 非法：{rec!r}")
            continue
        stats[rec] = stats.get(rec, 0) + 1
        fp = str(r.get("fingerprint", ""))
        if rec in ("纳入", "观察"):
            ev = r.get("evidence") or {}
            if not (str(ev.get("quote", "")).strip() and str(ev.get("url", "")).strip()):
                problems.append(f"{bid} evidence 缺失（纳入/观察必附 quote+url）")
        if rec != "重复":
            if fp in seen_fp:
                problems.append(f"{bid} 指纹重复：与第{seen_fp[fp]}条同指纹却均未标「重复」")
            seen_fp[fp] = i
        if rec == "排除" and not str(r.get("reason", "")).strip():
            problems.append(f"{bid} 排除行缺理由")
    return {"pass": not problems, "stats": stats, "problems": problems}


def selftest() -> int:
    good = [json.loads(l) for l in (SAMPLE / "scored_good.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    bad = [json.loads(l) for l in (SAMPLE / "scored_bad.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    rg, rb = validate(good), validate(bad)
    if not rg["pass"]:
        print(f"❌ 自测失败：干净样本应通过，实得 {rg['problems']}")
        return 1
    if rb["pass"]:
        print("❌ 自测失败：缺陷样本应被拦截")
        return 1
    print(f"✅ validate_leads 自测通过：干净样本 {rg['stats']['total']} 条通过；缺陷样本拦截 {len(rb['problems'])} 项。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="scout 产物转正机检")
    ap.add_argument("--file", default=str(LEADS))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    p = Path(a.file)
    if not p.exists():
        print(f"待检文件不存在：{p}（bid-scout 产出于 ~/.bidmaster/leads/scored.jsonl）")
        return 0
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    rep = validate(rows)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(f"统计：{rep['stats']}")
        for pr in rep["problems"]:
            print("  -", pr)
    if rep["pass"]:
        print("✅ 通过：可进入人工转正流程（lead.promote，L3）。", file=sys.stderr)
        return 0
    print("⛔ 存在拦截项，不得转正。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
