#!/usr/bin/env python3
"""lifecycle.py · lead 商机生命周期与维度判定（确定性规则，无 LLM）

七段生命周期（owner 2026-09-12 定）：线索期 → 发标 → 投标 → 述标 → 公示 → 交付 → 回款。
「其他语义归类」原则：判定器只依据证据字符串做保守归类，绝不含糊造态——
  - 有明确中标/公示证据 → 公示；中标方为我方（某网络安全服务商系）→ 交付；
  - 投标/回款这类「我方动作」阶段主要由人工经 lead.patch 推进，判定器不代设；
  - 证据不足以归类时落到最近似段，且原始 类型/状态 文本始终保留在 reason 可回溯。

供两侧共用：
  - rules/import_xlsx_leads.py（导入/upsert 时派生 phase / buyer_level / sub_industry / recommend）
  - server.py（lead.patch 校验 phase 合法值）
"""

PHASES = ["线索期", "发标", "投标", "述标", "公示", "交付", "回款"]
PHASE_ORDER = {p: i for i, p in enumerate(PHASES)}

# 我方（某网络安全服务商体系）中标识别词——命中即视为「我们赢了」进交付段
OUR_WIN_KEYWORDS = ("某网络安全服务商", "某网络安全服务商", "SEC", "sec")

# 细分行业关键词 → 行业（按序命中，越靠前越优先）
_SUB_INDUSTRY_RULES = [
    ("征信", "征信"),
    ("支付", "支付清算"), ("清算", "支付清算"), ("结算", "支付清算"), ("票据", "支付清算"),
    ("交易所", "交易所"), ("股交", "交易所"),
    ("金融科技", "金融科技"), ("金科", "金融科技"), ("数科", "金融科技"), ("科技", "金融科技"),
    ("保险", "保险"), ("寿险", "保险"), ("财险", "保险"), ("养老", "保险"),
    ("证券", "证券"), ("券商", "证券"),
    ("基金", "基金"),
    ("信托", "信托"),
    ("期货", "其他金融"), ("租赁", "其他金融"), ("消费金融", "其他金融"), ("汽车金融", "其他金融"), ("资管", "资产管理"), ("资产管理", "资产管理"), ("投资", "资产管理"),
    ("银行", "银行"), ("央行", "银行"), ("人民银行", "银行"), ("农信", "银行"), ("联社", "银行"), ("存款保险", "银行"),
]


def classify_phase(type_str: str = "", status_str: str = "", title_str: str = "",
                   winner_str: str = "") -> str:
    """从报告 类型/状态/标题/中标方 证据串归类七段生命周期（保守，就近归类）。"""
    t, s, ti, w = (type_str or ""), (status_str or ""), (title_str or ""), (winner_str or "")
    blob = f"{t} {s} {ti} {w}"
    # 我方中标 → 交付（其余中标 → 公示）
    if any(k in blob for k in ("中标结果", "已中标", "结果公示", "候选人公示", "中标候选人")):
        if any(k in w for k in OUR_WIN_KEYWORDS) or any(k in s for k in OUR_WIN_KEYWORDS):
            return "交付"
        return "公示"
    if "已截止" in t or "已截止" in s:
        return "述标"  # 截止已过、结果未出=评标窗口，就近归述标段
    if "单一来源" in blob:
        return "发标"
    if "招标公告" in blob or "磋商公告" in blob or "询价" in blob:
        return "发标"
    # 新增/持续跟进/无类型：按状态与标题里的采购动作词就近归位
    if any(k in blob for k in ("征集", "意向", "计划", "需求调查", "调研", "预算", "拟采购", "供应商库")):
        return "线索期"
    if any(k in blob for k in ("开标", "评审", "评标", "答辩", "述标", "磋商")):
        return "述标"
    if any(k in blob for k in ("公告", "报名", "招标文件", "招标", "投标", "截止")):
        return "发标"
    return "线索期"  # 兜底：证据不足按最早段处理，人工可经 lead.patch 推进


def buyer_level(org_type: str = "", buyer: str = "") -> str:
    """招标方级别：机构类型列原样最可信；缺失时按采购方名称关键词推断。"""
    ot = (org_type or "").strip()
    if ot:
        return ot
    b = buyer or ""
    for kw, level in (
        ("人民银行", "央行系"), ("央行", "央行系"), ("征信", "央行系"),
        ("国有", "国有大行"), ("工商银行", "国有大行"), ("农业银行", "国有大行"),
        ("中国银行", "国有大行"), ("建设银行", "国有大行"), ("交通银行", "国有大行"), ("邮储", "国有大行"),
        ("农商", "农商行"), ("农信", "农商行"), ("城商", "城商行"), ("村镇", "村镇银行"),
        ("证券", "证券公司"), ("保险", "保险机构"), ("基金", "基金公司"), ("信托", "信托公司"),
        ("交易", "交易所"), ("清算", "金融基础设施"), ("结算", "金融基础设施"), ("支付", "支付机构"),
    ):
        if kw in b:
            return level
    return "其他"


def sub_industry(buyer: str = "", org_type: str = "") -> str:
    """招标方细分行业（顶层扇区），供排序/统计维度用。"""
    blob = f"{buyer or ''} {org_type or ''}"
    for kw, ind in _SUB_INDUSTRY_RULES:
        if kw in blob:
            return ind
    return "其他"


def derive_priority(phase: str, amount_wan: float = 0.0) -> str:
    """规则化优先级（透明可复核；人工可随时 lead.patch/qualify 覆盖）。

    P1=值得立即投入，P2=观察储备；P0 保留给 scout/人工（不代设，
    避免触发 M3 自动升级路径）。判定依据：越靠近「我方还要动作」的段越优先，
    公示/交付/回款属已定局或经营段，一律 P2 情报位。
    """
    if phase in ("投标", "述标"):
        return "P1"
    if phase == "发标":
        return "P1" if amount_wan >= 100 else "P2"
    if phase == "线索期":
        return "P1" if amount_wan >= 500 else "P2"
    return "P2"  # 公示/交付/回款/未知


def selftest() -> None:
    cases = [
        (("✅结果公示", "已中标（绿盟）", "", "北京神州绿盟科技有限公司"), "公示"),
        (("✅结果公示", "已中标（某网络安全服务商）", "", "某网络安全服务商"), "交付"),
        (("⚠️已截止", "", "", ""), "述标"),
        (("🆕新增", "供应商征集", "xx征集公告", ""), "线索期"),
        (("招标公告", "", "", ""), "发标"),
        (("单一来源公示", "", "", ""), "发标"),
        (("", "开标评审中", "", ""), "述标"),
        (("", "", "某银行2026安全服务招标项目", ""), "发标"),
        (("", "", "某公司拟采购安全服务", ""), "线索期"),
    ]
    for args, want in cases:
        got = classify_phase(*args)
        assert got == want, f"classify_phase{args} = {got}, want {want}"
    assert buyer_level("城商行", "") == "城商行"
    assert buyer_level("", "中国人民银行征信中心") == "央行系"
    assert sub_industry("泰康养老保险股份有限公司", "") == "保险"
    assert sub_industry("某金融结算机构", "") == "支付清算"
    assert sub_industry("某农商银行", "农商行") == "银行"
    assert derive_priority("投标", 30) == "P1"
    assert derive_priority("发标", 50) == "P2"
    assert derive_priority("发标", 200) == "P1"
    assert derive_priority("线索期", 800) == "P1"
    assert derive_priority("公示", 900) == "P2"
    print(f"✅ lifecycle 自测通过：{len(cases)} 相位断言 + 维度/优先级断言")


if __name__ == "__main__":
    selftest()
