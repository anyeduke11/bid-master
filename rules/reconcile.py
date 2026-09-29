#!/usr/bin/env python3
"""reconcile.py · 真相源一致性守护（P0-3 · make gate 挂载）

检查项：
  1. 真实标生产层产物 ⊆ artifacts 登记（登记制：文件在而未登记=漂移）
（DEV-0081 收尾：jsonl 对账已随 v1.0 退役；projection.db 比对已随 rebuild_cache 化石
 清理一并移除——服务从不读 projection，它只制造"滞后警告"的噪音。）
用法：python3 rules/reconcile.py --check（exit 1=有漂移）；不带参数打印帮助。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store

DATA = store.DATA_ROOT


def check() -> list:
    problems = []
    store.init()
    truth = {b["bid_id"]: b["stage"] for b in store.load_bids()}

    # 登记制：真实标生产层产物 ⊆ artifacts
    c = store._conn()
    registered = {(r["bid_id"], r["path"]) for r in
                  c.execute("SELECT bid_id, path FROM artifacts")}
    bids_dir = DATA / "bids"
    if bids_dir.exists():
        for bid_dir in sorted(p for p in bids_dir.iterdir() if p.is_dir()):
            if bid_dir.name not in truth:
                problems.append(f"工作区存在但真实层无记录：{bid_dir.name}")
                continue
            if truth[bid_dir.name] in ("S0", "S1"):
                continue  # 未入编制期的标不要求登记
            for f in bid_dir.rglob("*.json"):
                rel = str(f)
                if (bid_dir.name, rel) not in registered and "source" not in f.parts:
                    problems.append(f"未登记产物：{rel}（store.register_artifact）")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="真相源一致性守护")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if not a.check:
        ap.print_help()
        return 3
    problems = check()
    if problems:
        print("⛔ 真相源漂移：")
        for p in problems[:20]:
            print("  -", p)
        return 1
    print("✅ reconcile：truth.db 与生产层登记制 全一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
