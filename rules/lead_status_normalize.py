#!/usr/bin/env python3
"""lead_status_normalize.py · 标讯 5 态状态机（owner 2026-09-13 定）

五态定义（数据层；看板只露 3 态，其它作为沉淀喂 06 经营分析）：
  tender      招标 / 磋商 / 征集 进行中
  publicity   中标候选人 / 成交候选人 / 评标 结果公示
  awarded     已中标 / 已成交 / 已中选 / 已入围（含公示期满转正）
  delivered   项目交付中 / 履约中 / 合同已签
  closed      招标失败 / 流标 / 废标 / 项目终止

入参任意中文字符串（xlsx、scout 工单、人工文本皆可），返回五态码 + 命中关键词。
关键字匹配遵循"最长前缀优先"，避免 "招标失败" 被 "招标" 抢先匹配到 tender。

CLI：
  python3 rules/lead_status_normalize.py "<状态原文>"
  python3 rules/lead_status_normalize.py --self-test
"""

from __future__ import annotations
import re
import sys

# 关键字表（按长度倒序，长的优先匹配）
# 顺序敏感：先列判定更"终结"的形态，再列仍在进行的
KEYWORDS: list[tuple[str, str]] = [
    # ── closed：终态，先判
    ("招标失败", "closed"),
    ("流标", "closed"),
    ("废标", "closed"),
    ("项目终止", "closed"),
    ("取消采购", "closed"),
    ("采购终止", "closed"),
    # ── delivered：合同阶段（公示期满转正、合同公告、履约中）
    ("合同公告", "delivered"),
    ("合同已签", "delivered"),
    ("履约中", "delivered"),
    ("项目交付", "delivered"),
    ("交付中", "delivered"),
    # ── awarded：已出结果
    ("采购结果公告", "awarded"),
    ("中标结果公告", "awarded"),
    ("中标结果公示期满", "awarded"),
    ("成交结果公告", "awarded"),
    ("成交结果公示期满", "awarded"),
    ("中标公告", "awarded"),
    ("成交公告", "awarded"),
    ("中选结果公告", "awarded"),
    ("已中标", "awarded"),
    ("已成交", "awarded"),
    ("已中选", "awarded"),
    ("已入围", "awarded"),
    ("中标(", "awarded"),  # "中标(08-18)" 等含括号的简写
    ("成交(", "awarded"),
    # ── publicity：候选人/结果公示（仍在公示期、未转 awarded）
    ("中标候选人公示", "publicity"),
    ("成交候选人公示", "publicity"),
    ("中标候选公示", "publicity"),
    ("成交候选公示", "publicity"),
    ("中标结果公示", "publicity"),
    ("成交结果公示", "publicity"),
    ("中标公示", "publicity"),
    ("成交公示", "publicity"),
    ("评标结果公示", "publicity"),
    ("候选人公示", "publicity"),
    ("入围候选人公示", "publicity"),
    ("单一来源公示", "publicity"),  # 公示期未结束
    ("中标候选", "publicity"),     # 短形（"中标候选"裸词）
    # ── tender：进行中（最后判；"招标失败" 已被 closed 优先吃掉）
    ("招标中", "tender"),
    ("磋商中", "tender"),
    ("征集中", "tender"),
    ("采购中", "tender"),
    ("邀请中", "tender"),
    ("招标公告", "tender"),
    ("采购公告", "tender"),
    ("磋商公告", "tender"),
    ("征集公告", "tender"),
    ("采购邀请", "tender"),
    ("资格预审", "tender"),
    ("遴选公告", "tender"),
    ("POC测试公告", "tender"),
    ("招标公告发布", "tender"),
    ("邀请招标公告", "tender"),
    ("竞争性磋商公告", "tender"),
    ("公开询价公告", "tender"),
    ("候选供应商再次征集", "tender"),
    ("征集/比选中", "tender"),
    ("报名已截止", "tender"),
    ("已截止", "publicity"),  # "已截止待结果"=刚截止等开评；归 publicity
]


def normalize(text: str) -> tuple[str, str]:
    """返回 (五态码, 命中关键词)；未知→('unknown', '')。"""
    if not text:
        return ("unknown", "")
    s = str(text).strip()
    # 直接 contains 命中（按 KEYWORDS 顺序，先命中先返；列表本身按优先级排序）
    for kw, code in KEYWORDS:
        if kw in s:
            return (code, kw)
    return ("unknown", "")


# ---------- CLI ----------

def _selftest() -> int:
    cases = [
        # (input, expected_code)
        ("招标中", "tender"),
        ("招标公告（2026-09-03发布；投标截止2026-09-16 9:00）", "tender"),
        ("磋商中（磋商文件获取 2026-08-31 ~ 2026-09-04；响应文件递交截止 2026-09-10 10:00）（已截止待结果）", "tender"),
        ("征集中", "tender"),
        ("采购邀请（山西省分行；谈判时间由09-09调整至09-11）", "tender"),
        ("招标中（已截止待结果）", "tender"),
        # publicity
        ("中标候选人公示", "publicity"),
        ("中标候选人公示(08-05~08-11)", "publicity"),
        ("中标候选公示(公示至2026-08-31)", "publicity"),
        ("评标结果公示", "publicity"),
        ("候选人公示（2026-09-02~09-08）", "publicity"),
        ("成交结果公示（2026-09-09~09-14）", "publicity"),
        ("单一来源公示(08-07~08-10)", "publicity"),
        # awarded
        ("已中标", "awarded"),
        ("已中标(公示期满 2026-08-27)", "awarded"),
        ("已中标(公安部第三研究所,100万,08-11)", "awarded"),
        ("已成交", "awarded"),
        ("已中选", "awarded"),
        ("中标(08-18)", "awarded"),
        ("中标公告（2026-09-03，211万元）", "awarded"),
        ("中标结果公告（2026-09-01）", "awarded"),
        ("采购结果公告（2026-09-03）", "awarded"),
        # delivered
        ("合同公告（2026-09-01）", "delivered"),
        ("履约中", "delivered"),
        # closed
        ("招标失败(2家串通投标否决,有效投标不足3家,08-14)", "closed"),
        ("流标", "closed"),
        # unknown / 噪声
        ("状态", "unknown"),
        ("", "unknown"),
    ]
    fails = 0
    for txt, expected in cases:
        got, kw = normalize(txt)
        ok = got == expected
        flag = "✓" if ok else "✗"
        if not ok: fails += 1
        print(f"{flag} {got:9s} (kw={kw!r:24s}) ← {txt[:60]!r}")
    print()
    if fails:
        print(f"❌ selftest 失败 {fails}/{len(cases)}")
        return 1
    print(f"✅ selftest 通过 {len(cases)}/{len(cases)}")
    return 0


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test":
        sys.exit(_selftest())
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    code, kw = normalize(sys.argv[1])
    print(f"code={code}  matched={kw!r}  input={sys.argv[1]!r}")


if __name__ == "__main__":
    main()