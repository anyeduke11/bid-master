#!/usr/bin/env python3
"""locator_sample.py · 定位抽查机械采样器（DEV-0057）

用途：为 S5→S6 门禁生成可复算的 locator-report（samples schema v2）。
背景：bid-locator 子智能体模型不可用时的确定性替代——逐字子串比对完全可复算，
无 LLM 判断参与；与 set_stage.gate_s5_s6 的复算口径完全一致（去空白后子串匹配）。

采样总体（SKILL §2 口径——只采「声称的原文引用」，写手叙述句不入样）：
  A. 规格 spec.json 全部评分点 requirement 的『』内层原文（响应段逐字引用位）；
  B. 每章 ≤3 条「带引号包装的声称引用」（『』或 “”），修辞引号经 EXCLUDE 排除。

用法：
  python3 rules/locator_sample.py --bid <bid_id> [--out verify/locator-report.json]

输出：报告 JSON 打印到 stdout；--out 时同时写盘（不登记——登记由调用方
store.register_artifact(kind='locator', status='registered', producer=…) 完成）。
注意：miss 需人工定性（表格线性化损耗 / 引用拼接漂移），报告只是机器事实。
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

DATA_ROOT = Path(os.environ["BIDMASTER_HOME"]) if "BIDMASTER_HOME" in os.environ else Path.home() / ".bidmaster"


def unwrap(s: str) -> str:
    """剥掉规格单标注包装：取『…』内层原文（tender.txt 只含内层）。"""
    m = re.search(r"『([^』]+)』", s)
    return m.group(1) if m else s


def sample(bid_id: str) -> dict:
    ws = DATA_ROOT / "bids" / bid_id
    drafts = sorted((ws / "draft").glob("ch-*.md"))
    tender_flat = re.sub(r"\s+", "", (ws / "source" / "tender.txt").read_text(encoding="utf-8", errors="replace"))
    spec = json.loads((ws / "data" / "spec.json").read_text(encoding="utf-8"))
    samples = []
    excluded = []
    # 每标排除清单（人工 locator 判断落痕）：verify/locator-exclude.json = [{quote, reason}]
    # 口径 = SKILL §2「排除」：写手修辞引号/表格损耗可判定项，不入样本不计分母，但留痕不隐藏
    excl_p = ws / "verify" / "locator-exclude.json"
    exclude_quotes = {}
    if excl_p.exists():
        for e in json.loads(excl_p.read_text(encoding="utf-8")):
            exclude_quotes[re.sub(r"\s+", "", str(e.get("quote", "")))] = str(e.get("reason", ""))

    # A. 评分点 requirement 全采样（剥『』包装后取原文内层）
    for pt in spec.get("scoring_points") or []:
        req = unwrap(str(pt.get("requirement", "")).strip())
        if len(req) < 8:
            continue
        q = req[:40]
        samples.append({"chapter": pt.get("chapter", "?"), "quote": q,
                        "hit": re.sub(r"\s+", "", q) in tender_flat,
                        "note": "规格 requirement 内层原文（响应段逐字引用位）"})

    # B. 每章「带引号包装的声称引用」采样（≤3 条/章）
    quote_seg = re.compile(r"[『\u201c]([^『』\u201c\u201d]{12,120})[』\u201d]")
    for d in drafts:
        ch = d.stem
        text = re.sub(r"<!--.*?-->", "", d.read_text(encoding="utf-8", errors="replace"), flags=re.DOTALL)
        segs = []
        for m in quote_seg.finditer(text):
            seg = re.sub(r"\s+", "", m.group(1))
            if len(seg) >= 12 and seg not in segs:
                segs.append(seg)
        for seg in segs[:3]:
            if seg in exclude_quotes:
                excluded.append({"chapter": ch, "quote": seg[:40], "reason": exclude_quotes[seg]})
                continue
            samples.append({"chapter": ch, "quote": seg[:40],
                            "hit": seg in tender_flat, "note": "草稿引号包装的声称引用"})

    hits = sum(1 for s in samples if s["hit"])
    rate = round(hits / len(samples), 4) if samples else 0.0
    return {"bid_id": bid_id, "sampled": len(samples), "hits": hits, "hit_rate": rate,
            "method": "mechanical-verbatim（rules/locator_sample.py：确定性子串比对，口径同门禁复算）",
            "excluded": excluded,
            "samples": samples}


def main() -> int:
    ap = argparse.ArgumentParser(description="定位抽查机械采样器（可复算 locator-report）")
    ap.add_argument("--bid", required=True)
    ap.add_argument("--out", default="", help="写盘路径（相对 bids/<bid>/，如 verify/locator-report.json）")
    a = ap.parse_args()

    report = sample(a.bid)
    if a.out:
        out_p = DATA_ROOT / "bids" / a.bid / a.out
        out_p.parent.mkdir(parents=True, exist_ok=True)
        # status 为 locator 契约必填（registered → 门禁通过后由 set_stage 提升 final）
        out_p.write_text(json.dumps({**report, "status": "registered"}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"[locator_sample] 报告 → {out_p}", file=sys.stderr)
        # DEV-0057：登记制纪律——落盘即登记（排除清单与报告都登记，reconcile 抓未登记产物）
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import store
            store.init()
            excl_p = DATA_ROOT / "bids" / a.bid / "verify" / "locator-exclude.json"
            if excl_p.exists():
                print(store.register_artifact(a.bid, "locator_exclude", str(excl_p), producer="bid-locator"), file=sys.stderr)
            print(store.register_artifact(a.bid, "locator", str(out_p), status="registered", producer="bid-locator"), file=sys.stderr)
        except Exception as e:
            print(f"[locator_sample] 登记失败（可手动 store.register_artifact）：{e}", file=sys.stderr)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    missed = [s for s in report["samples"] if not s["hit"]]
    print(f"\n[sampler] 共 {report['sampled']} 条，命中 {report['hits']}，"
          f"hit_rate={report['hit_rate']:.2%}，miss {len(missed)} 条", file=sys.stderr)
    for s in missed[:10]:
        print(f"  MISS [{s['chapter']}] {s['quote'][:36]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
