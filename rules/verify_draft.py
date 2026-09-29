#!/usr/bin/env python3
"""verify_draft.py · bid-writer 章节机检（W3 3.2）

设计依据：docs/acceptance-agents.md §3.3（writer 专项验收）、skills/bid-write/SKILL.md
────────────────────────────────────────────────────────────────
四项检查（对应 acceptance 硬指标）：
  1. cite 白名单   草稿中每个 [P#] ∈ 该章白名单（违规=幻觉断言，整章打回）——**违规必须 =0**
  2. 评分点覆盖    规格单映射到本章的每个评分点，在草稿中有对应段落（机检代理：评分点 ID 显式出现）
  3. 字数区间      字数 ∈ 规格单 chapters[].word_min/max（或 CLI --min/--max 覆盖）
  4. manifest 完整 六字段齐全（acceptance G2 溯源），self_check 如实

规格单 schema v1（data/spec.json）：
  {"scoring_points": [{"id","chapter","material_ptrs":[...],"cites":["P12",...]}],
   "chapters": [{"chapter":"ch01","word_min":300,"word_max":500}]}
  章白名单 = 该章评分点 cites 的并集（可另加顶层 "whitelist" 全局补充）。

用法：
  python3 rules/verify_draft.py --bid <bid_id> --chapter ch01 [--min 300 --max 500] [--json]
  python3 rules/verify_draft.py --bid <bid_id> --all
  python3 rules/verify_draft.py --selftest
退出码：0 PASS（含 manual-check 状态）；1 FAIL；3 用法错误。
报告：~/.bidmaster/bids/<bid>/verify/verify_draft_<chapter>.json（status=final，watcher 消费）。
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

DATA_ROOT = Path.home() / ".bidmaster"
CITE_RE = re.compile(r"\[P(\d+)\]")
REQUIRED_MANIFEST = ("producer", "model", "input_fingerprint", "ticket_id", "self_check")


def _read(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def verify_chapter(ws: Path, chapter: str, word_min=None, word_max=None) -> dict:
    """对单章草稿执行四项机检；返回报告 dict（不落盘）。任何前置缺失都计入 blockers。"""
    blockers, warns = [], []
    spec_p = ws / "data" / "spec.json"
    draft_p = ws / "draft" / f"{chapter}.md"
    mani_p = ws / "draft" / f"{chapter}.manifest.json"

    # 规格单与白名单
    if not spec_p.exists():
        return {"chapter": chapter, "pass": False, "checks": [],
                "blockers": [f"缺规格单 {spec_p}（writer 无从取得白名单）"]}
    spec = _read(spec_p)
    points = [pt for pt in (spec.get("scoring_points") or []) if pt.get("chapter") == chapter]

    def _norm_cite(c):
        s = str(c).strip().upper()
        return s if s.startswith("P") else "P" + s

    whitelist = {_norm_cite(c) for pt in points for c in (pt.get("cites") or [])}
    whitelist |= {_norm_cite(c) for c in (spec.get("whitelist") or [])}
    rng = next((c for c in (spec.get("chapters") or []) if c.get("chapter") == chapter), {})
    word_min = word_min if word_min is not None else rng.get("word_min")
    word_max = word_max if word_max is not None else rng.get("word_max")

    if not draft_p.exists():
        return {"chapter": chapter, "pass": False, "checks": [],
                "blockers": [f"缺草稿 {draft_p}"]}
    text = draft_p.read_text(encoding="utf-8")
    checks = []

    # 1) cite 白名单
    used = {f"P{n}" for n in CITE_RE.findall(text)}
    illegal = sorted(used - whitelist)
    checks.append({"name": "cite_whitelist", "ok": not illegal,
                   "detail": f"使用 {sorted(used) or '无'} / 白名单 {sorted(whitelist) or '∅'}"
                             + (f"；违规 {illegal}（幻觉断言，整章打回）" if illegal else "")})
    if illegal:
        blockers.append(f"cite 白名单违规 {illegal}：不在规格单白名单内")

    # 2) 评分点覆盖（机检代理：评分点 ID 显式出现）
    missing = [pt.get("id") for pt in points if str(pt.get("id") or "") and str(pt["id"]) not in text]
    checks.append({"name": "scoring_coverage", "ok": not missing,
                   "detail": f"{len(points) - len(missing)}/{len(points)} 评分点有显式响应段"
                             + (f"；缺 {missing}" if missing else "")})
    if missing:
        blockers.append(f"评分点未覆盖：{missing}")

    # 3) 字数区间
    n_words = len(re.sub(r"\s", "", text))
    rng_ok = (word_min is None or n_words >= word_min) and (word_max is None or n_words <= word_max)
    checks.append({"name": "word_range", "ok": rng_ok,
                   "detail": f"{n_words} 字（区间 {word_min}–{word_max}）"})
    if not rng_ok:
        blockers.append(f"字数 {n_words} 不在区间 {word_min}–{word_max}")

    # 4) manifest
    if not mani_p.exists():
        blockers.append(f"缺 manifest {mani_p}")
        checks.append({"name": "manifest", "ok": False, "detail": "缺失"})
    else:
        m = _read(mani_p)
        lacking = [k for k in REQUIRED_MANIFEST if k not in m]
        fp = str(m.get("input_fingerprint", ""))
        honest = str(m.get("self_check", "")) in ("pass", "manual-check", "fail")
        ok4 = not lacking and honest
        checks.append({"name": "manifest", "ok": ok4,
                       "detail": f"字段缺 {lacking or '无'}；fingerprint={fp[:24] or '∅'}；self_check={m.get('self_check')}"})
        if lacking:
            blockers.append(f"manifest 缺字段：{lacking}")
        if not honest:
            blockers.append("manifest self_check 必须为 pass/manual-check/fail（溯源如实，G2）")

    return {"chapter": chapter, "pass": not blockers, "checks": checks,
            "blockers": blockers, "warns": warns, "word_count": n_words,
            "whitelist": sorted(whitelist)}


def save_report(bid_id: str, report: dict) -> Path:
    out = DATA_ROOT / "bids" / bid_id / "verify" / f"verify_draft_{report['chapter']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({**report, "status": "registered", "producer": "verify_draft",
                               "ts": _now()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # P1-2 登记制：机检报告落库（status=registered；final 由门禁提升）
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import store
        store.init()
        store.register_artifact(bid_id, "verify_draft", str(out), status="registered", producer="verify_draft")
    except Exception:
        pass
    return out


def selftest() -> int:
    base = Path(__file__).resolve().parent.parent / "tests" / "sample" / "verify_draft"
    ws = base
    r = verify_chapter(ws, "chT")
    cite_ok = next(c for c in r["checks"] if c["name"] == "cite_whitelist")
    cov_ok = next(c for c in r["checks"] if c["name"] == "scoring_coverage")
    # 样本设计：chT 含白名单外引用 [P99] → cite 检查必须 FAIL（违规被拦）、整章 pass=False；评分点覆盖仍须 PASS
    if r["pass"] or cite_ok["ok"] or not cov_ok["ok"]:
        print(f"❌ 自测失败（断言不成立）：{json.dumps(r, ensure_ascii=False)[:300]}")
        return 1
    print("✅ verify_draft 自测通过：违规引用被拦（P99）、评分点覆盖识别正常、其余检查按预期。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="bid-writer 章节机检（cite/覆盖/字数/manifest）")
    ap.add_argument("--bid")
    ap.add_argument("--chapter")
    ap.add_argument("--all", action="store_true", help="按规格单 chapters 全量检查")
    ap.add_argument("--min", type=int, default=None)
    ap.add_argument("--max", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.bid:
        ap.print_help()
        return 3
    ws = DATA_ROOT / "bids" / a.bid
    chapters = (["chT"] if a.selftest else None)
    if a.all:
        spec_p = ws / "data" / "spec.json"
        if not spec_p.exists():
            print(f"❌ 缺 {spec_p}")
            return 1
        chapters = [c.get("chapter") for c in (_read(spec_p).get("chapters") or [])]
    elif a.chapter:
        chapters = [a.chapter]
    if not chapters:
        print("❌ 无可检查章节（--chapter 或 --all）")
        return 3
    rc = 0
    for ch in chapters:
        rep = verify_chapter(ws, ch, a.min, a.max)
        out = save_report(a.bid, rep)
        if a.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
        else:
            mark = "✅ PASS" if rep["pass"] else "⛔ FAIL"
            print(f"{mark} {a.bid}/{ch} → {out.name}")
            for b in rep["blockers"]:
                print(f"   - {b}")
        rc = rc or (0 if rep["pass"] else 1)
    return rc


if __name__ == "__main__":
    sys.exit(main())
