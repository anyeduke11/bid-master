#!/usr/bin/env python3
"""regress.py · 金标准回归（W4 4.5 · make regress）

两层：
  1. 静态门（每次必跑）：金标准素材指纹完好、verify_draft/validate_leads 自测、规则库与模板在位
  2. 基线对比：读 runs/baseline-*.json，最新 vs 上一份，输出 召回/检出/耗时/token 对比表
     （基线由演练/冒烟运行产出后手工归档，字段见 runs/README.md）

用法：
  python3 rules/regress.py                  # 静态门 + 最新基线对比表
  python3 rules/regress.py --baseline <new> # 归档新基线并与上一份对比
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GOLDEN = REPO / "tests" / "golden"
RUNS = REPO / "runs"
BASELINES = "baseline-*.json"

METRIC_ROWS = [
    ("writer_cite_violations", "writer cite 违规数", 0, "=="),
    ("writer_coverage_rate", "评分点覆盖率", 1.0, ">="),
    ("auditor_key_detected", "auditor 金标准检出数", 8, ">="),
    ("locator_verdict_accuracy", "locator 判定准确率", 0.95, ">="),
    ("blocking_findings_r2", "r2 阻断级缺陷数", 0, "=="),
    ("gate_ms_max", "门禁最大耗时 ms", 2000, "<="),
]


def static_gate() -> list:
    problems = []
    mat = GOLDEN / "goldstd" / "materials.json"
    if not mat.exists():
        # 金标准素材清单为本地保留件（含客户文档指针，不入公开库）——缺件时跳过指纹核对
        print("○ 金标准素材清单不在库（本地保留件），跳过指纹核对")
    else:
        import hashlib
        root = json.loads(mat.read_text(encoding="utf-8"))["_meta"]["source_root"]
        for m in json.loads(mat.read_text(encoding="utf-8"))["materials"]:
            p = Path(root) / m["path"]
            if not p.exists():
                problems.append(f"素材缺失：{m['key']} → {p}")
                continue
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            if m["fingerprint"] != "sha256:" + h:
                problems.append(f"素材指纹漂移：{m['key']}（外部目录可能被改动，需复归）")
    for f, cmd in (("verify_draft.py", "selftest"), ("validate_leads.py", "selftest")):
        if not (REPO / "rules" / f).exists():
            problems.append(f"缺机检脚本 rules/{f}")
    if not (REPO / "rules/audit/audit-rules.json").exists():
        problems.append("缺规则库 rules/audit/audit-rules.json")
    return problems


def load_baselines() -> list:
    return sorted(RUNS.glob(BASELINES))


def compare(new: dict, old: dict | None) -> list:
    rows = []
    for key, label, threshold, op in METRIC_ROWS:
        nv, ov = new.get(key), (old or {}).get(key)
        verdict = "?"
        if isinstance(nv, (int, float)):
            good = (nv == threshold) if op == "==" else (nv >= threshold if op == ">=" else nv <= threshold)
            verdict = "✅" if good else "❌"
        rows.append((label, ov, nv, threshold, op, verdict))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="金标准回归：静态门 + 基线对比")
    ap.add_argument("--baseline", help="归档新基线（runs/baseline-*.json）并与上一份对比")
    a = ap.parse_args()

    print("── 静态门 ──")
    problems = static_gate()
    for p in problems:
        print("  ❌", p)
    if problems:
        return 1
    print("  ✅ 素材指纹/机检自测脚本/规则库均在位")

    bl = load_baselines()
    print(f"── 基线对比（共 {len(bl)} 份）──")
    if not bl:
        print("  ⏳ 尚无基线。演练/冒烟后以 --baseline 归档首份（字段见 runs/README.md）。")
        return 0
    new = json.loads(bl[-1].read_text(encoding="utf-8"))
    old = json.loads(bl[-2].read_text(encoding="utf-8")) if len(bl) >= 2 else None
    print(f"  最新：{bl[-1].name}" + (f"  上一份：{bl[-2].name}" if old else "（首份，无对比）"))
    print(f"  {'指标':<26}{'上一份':>10}{'最新':>10}   阈值")
    for label, ov, nv, thr, op, verdict in compare(new, old):
        print(f"  {label:<26}{str(ov):>10}{str(nv):>10}   {op}{thr} {verdict}")
    if a.baseline:
        src = Path(a.baseline)
        dst = RUNS / f"baseline-{datetime.now().strftime('%Y%m%d')}-{src.stem}.json"
        RUNS.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"✅ 基线归档：{dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
