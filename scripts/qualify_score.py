#!/usr/bin/env python3
"""qualify_score.py · L2 资质预审 + AI 评分(v0.3.2 / DEV-0042 通路收敛)
- 输入: ~/.bidmaster/leads/raw/leads.jsonl（lead_capture.py 产出，唯一数据面）
- 输出: ~/.bidmaster/leads/qualify.jsonl (每条 lead + score + recommend)
- 回写: 由服务 M3 watcher 监听 qualify.jsonl 入库（本脚本不再跨进程直写 DB——反模式已移除）
- 算法(满分 100):
  行业:银行/政府+20, 证券/能源/金融+15
  区域:华南/华北/华东+10
  金额:100-500万+10, 500-1000万+15
  关键词命中:网络安全/SOC/态势感知/零信任/数据安全/云安全/SDP/等保/合规/工控/EDR/XDR/SecOps +8/个
  截止日:30天内+5
- 阈值:P0>=60, P1>=45, P2>=30, 跳过<30
"""
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

_DATA_ROOT = Path(os.environ.get("BIDMASTER_HOME") or (Path.home() / ".bidmaster"))
LEADS = _DATA_ROOT / "leads" / "raw" / "leads.jsonl"
OUT = _DATA_ROOT / "leads" / "qualify.jsonl"
DATA_DIR = _DATA_ROOT / "leads"


def _ensure_inside(base_dir, target):
    """路径穿越防护:目标文件解析后的真实路径必须位于 base_dir 之下,否则拒绝写入。"""
    base = Path(base_dir).resolve()
    t = Path(target).resolve()
    if t.parent != base and base not in t.parents:
        raise SystemExit(f"输出路径越界,拒绝写入: {target}")
    return t

TOP_INDUSTRY = ("银行", "政府")
GOOD_INDUSTRY = ("金融", "证券", "能源", "医疗", "教育", "电信")
PREFERRED_REGION = ("华南", "华北", "华东")
PREFERRED_KEYWORDS = ("网络安全", "SOC", "态势感知", "零信任", "数据安全", "云安全", "SDP", "等保", "合规", "工控", "EDR", "XDR", "SecOps")

def score_lead(lead):
    s = 0; reasons = []
    industry = lead.get("industry", "")
    if industry in TOP_INDUSTRY:
        s += 20; reasons.append(f"优质行业({industry}+20)")
    elif industry in GOOD_INDUSTRY:
        s += 15; reasons.append(f"目标行业({industry}+15)")
    region = lead.get("region", "")
    if region in PREFERRED_REGION:
        s += 10; reasons.append(f"区域匹配({region}+10)")
    amount = lead.get("amount", 0) or 0
    if 100 <= amount <= 500:
        s += 10; reasons.append(f"金额合理({amount}万+10)")
    elif 500 < amount <= 1000:
        s += 15; reasons.append(f"大金额({amount}万+15)")
    elif amount > 0:
        s += 5; reasons.append(f"金额小({amount}万+5)")
    kw = lead.get("raw_keywords", "") or ""
    hit = sum(1 for k in PREFERRED_KEYWORDS if k in kw)
    if hit > 0:
        s += hit * 8; reasons.append(f"关键词命中({hit}个+{hit*8})")
    # 截止日紧迫度
    dl = lead.get("deadline", "")
    if dl:
        try:
            d = datetime.strptime(dl, "%Y-%m-%d").date()
            days = (d - date.today()).days
            if 0 <= days <= 30:
                s += 5; reasons.append(f"截止近({days}天+5)")
        except Exception: pass
    s = min(100, s)
    if s >= 60: rec = "P0"
    elif s >= 45: rec = "P1"
    elif s >= 30: rec = "P2"
    else: rec = "跳过"
    return s, rec, "; ".join(reasons)

def main():
    if not LEADS.exists():
        print(json.dumps({"ok": False, "err": f"leads 文件不存在: {LEADS}"}, ensure_ascii=False))
        sys.exit(1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # 覆盖写(避免重复累积)
    qualified = []
    with open(LEADS, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            lead = json.loads(line)
            s, rec, reason = score_lead(lead)
            out = {**lead, "score": s, "recommend": rec, "reason": reason}
            qualified.append(out)
    # 一次性写,避免半截文件(路径穿越防护:规范化后必须位于 ~/.bidmaster/leads 之下,且不含 ..)
    base_real = os.path.realpath(str(DATA_DIR))
    out_real = os.path.realpath(os.path.normpath(str(_ensure_inside(DATA_DIR, OUT))))
    if ".." in str(OUT) or not out_real.startswith(base_real + os.sep):
        raise SystemExit(f"输出路径越界,拒绝写入: {OUT}")
    content = "".join(json.dumps(q, ensure_ascii=False) + "\n" for q in qualified)
    Path(out_real).write_text(content, encoding="utf-8")
    by_rec = {"P0": 0, "P1": 0, "P2": 0, "跳过": 0}
    for q in qualified: by_rec[q["recommend"]] += 1
    # DEV-0042：不再跨进程直写 bidboard.db（~/.bidboard 已退役）——
    # 服务 M3 watcher 监听本脚本输出的 qualify.jsonl 统一入库。
    print(json.dumps({"ok": True, "module": "qualify_score", "scored": len(qualified), "by_recommend": by_rec, "out": str(OUT)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
