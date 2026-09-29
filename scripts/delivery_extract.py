#!/usr/bin/env python3
"""delivery_extract.py · L4 合同要素抽取
- 输入: 合同 PDF/文本(参数传入)
- 输出: 合同要素 JSON(合同号/签订日/交付期/金额/产品)
- 当前: mock 模式,从环境变量读取合同内容并生成要素
"""
import json
import os
import sys
from pathlib import Path

def main():
    contract_text = os.environ.get("CONTRACT_TEXT", "")
    if not contract_text:
        # mock:基于 bid code 返回默认要素
        bid_code = sys.argv[1] if len(sys.argv) > 1 else "unknown"
        result = {
            "ok": True, "module": "delivery_extract", "bid_code": bid_code,
            "contract_no": f"{bid_code.upper()}-HT-2026-001",
            "signed_at": "2026-08-15",
            "kickoff_at": "2026-08-20",
            "delivery_months": 6,
            "amount": 480,
            "products": ["态势感知平台", "数据安全合规咨询"],
            "milestones": [
                {"name": "启动会", "date": "2026-08-20"},
                {"name": "需求确认", "date": "2026-09-10"},
                {"name": "系统部署", "date": "2026-10-30"},
                {"name": "初验", "date": "2026-12-15"},
                {"name": "终验", "date": "2027-02-28"},
            ],
            "warranty_months": 12,
            "source": "mock",
        }
    else:
        # 真实模式:从 contract_text 抽取(此处占位)
        result = {"ok": True, "module": "delivery_extract", "err": "真实抽取未实现,需要 LLM 接入", "text_len": len(contract_text)}
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
