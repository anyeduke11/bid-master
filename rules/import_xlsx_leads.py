#!/usr/bin/env python3
"""import_xlsx_leads.py · 标讯 xlsx 报告导入（W4 收割补充路径）

把外部采集的标讯 xlsx（如 WorkBuddy/Claw 产出的《金融行业网络安全标讯数据报告》）
转成 JSON 中间产物，再**选择性**填充关键数据，经看板既有 `collection.sync`
幂等命令管道入库（观察层 leads，非 truth.db；线索升级仍走 lead.promote L3）。

设计约定（对齐 PRD v6 §7「给路径和目标，不内嵌大段内容」与 v0.3.2 关闭区纪律）：
  1. xlsx → JSON：全 16 列清洗（HYPERLINK 公式抽 URL、金额归一、日期归一），
     中间产物落 ~/.bidmaster/leads/imports/<报告名>.json（可复算、可审计）；
  2. 选择性填充：只映射看板 leads 表的关键字段，不做评分/优先级编造
     （score/recommend 留空，评分归 bid-scout，人工确认归 lead.qualify）；
  3. 入库幂等：lead_id = sha256(title|buyer) 确定性派生，重跑同报告零重复；
  4. 过期归档：入库后触发看板时效扫描，发布超期的自动进关闭区（Duke 2026-08-15 严令）。

用法：
  python3 rules/import_xlsx_leads.py <file.xlsx>                 # 转JSON + 入库 + 时效扫描
  python3 rules/import_xlsx_leads.py <file.xlsx> --json-only     # 只转 JSON
  python3 rules/import_xlsx_leads.py <file.xlsx> --dry-run       # 打印映射样例，不入库
  python3 rules/import_xlsx_leads.py <file.xlsx> --types 新增,招标公告   # 按类型子集导入
"""

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "rules"))
import lifecycle  # noqa: E402  七段生命周期/细分行业/优先级判定（与 server.py lead.patch 共用）
try:
    import lead_status_normalize  # noqa: E402  5态状态机（DEV-0045）；不存在时降级仅写 status_text
except ImportError:
    lead_status_normalize = None
IMPORTS_DIR = Path.home() / ".bidmaster" / "leads" / "imports"

# 出网白名单：本工具唯一允许的请求目标 = 本机看板命令入口（PRD v6 §4 命令注册表）
KANBAN_ORIGIN = "http://127.0.0.1:8080"
KANBAN_HOSTS = {"127.0.0.1:8080"}

# xlsx「标讯明细」sheet 的表头列名 → 记录字段
COLUMNS = [
    "seq", "type", "title", "buyer", "summary", "service_type", "org_type",
    "published_at", "deadline", "amount_wan", "procurement", "status",
    "winner", "link_cell", "link_verified", "note",
]
HEADER_MARK = "序号"  # 表头行识别标记（报告前两行是标题/采集周期）
SKIP_TYPE_KEYWORDS = ("政策",)  # 政策资讯不是标讯线索，默认跳过


def extract_link(cell) -> str:
    """原文链接列兼容两种形态：=HYPERLINK("url","text") 公式 / 纯 URL 文本。"""
    if cell is None:
        return ""
    s = str(cell).strip()
    m = re.search(r'=HYPERLINK\(\s*"([^"]+)"', s)
    if m:
        return m.group(1).strip()
    if s.startswith(("http://", "https://")):
        return s
    return ""


def norm_date(s) -> str:
    """发布/截止日期归一：2026/07/06 → 2026-07-06（看板时效扫描按 [:10] 解析）。"""
    if s is None:
        return ""
    s = str(s).strip().replace("/", "-").replace(".", "-")
    m = re.match(r"(\d{4}-\d{1,2}-\d{1,2})", s)
    if not m:
        return s
    y, mo, d = m.group(1).split("-")
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def norm_amount(s) -> float:
    """金额(万元) → float；空/区间/非数字一律 0（不猜）。"""
    if s is None:
        return 0.0
    m = re.search(r"[\d.]+", str(s))
    return float(m.group(0)) if m else 0.0


def xlsx_to_records(xlsx_path: Path, sheet: str) -> list[dict]:
    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=False)
    ws = wb[sheet] if sheet in wb.sheetnames else wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    header_idx = next(
        (i for i, r in enumerate(rows) if r and any(str(c).strip() == HEADER_MARK for c in r if c)),
        None,
    )
    if header_idx is None:
        raise SystemExit(f"❌ 未找到表头行（缺「{HEADER_MARK}」列）: {xlsx_path}")

    records = []
    for r in rows[header_idx + 1:]:
        if r is None or r[0] is None:  # 空行/无序号
            continue
        rec = {k: r[i] for i, k in enumerate(COLUMNS) if i < len(r)}
        rec["title"] = str(rec.get("title") or "").strip()
        if not rec["title"]:
            continue
        rec["buyer"] = str(rec.get("buyer") or "").strip()
        rec["type"] = str(rec.get("type") or "").strip()
        rec["link"] = extract_link(rec.pop("link_cell", None))
        rec["published_at"] = norm_date(rec.get("published_at"))
        rec["deadline"] = str(rec.get("deadline") or "").strip()
        rec["amount_wan"] = norm_amount(rec.get("amount_wan"))
        records.append(rec)
    return records


# xlsx「标讯明细」sheet 的严格核心表头（owner 2026-09-13 定稿，基准样式 =
# 金融行业网络安全标讯数据报告_20260913.xlsx 的 16 列）。A 模式契约：
#   - 16 个核心列名必须精确出现且各恰一次，**顺序无关**（防的是名字歧义装错列，不是排列）
#   - 不许同义词、不许缺列；出现未知列即整体拒绝（防静默吞掉新列）
#   - 「招标代理」为可选列（存量报告无此列，有则提取）
STRICT_HEADERS = ("序号", "类型", "项目名称", "招标采购方", "内容总结", "服务类型",
                  "机构类型", "发布时间", "截止/公示日期", "金额(万元)", "采购方式",
                  "状态", "中标方/候选人", "原文链接", "链接核实", "备注")
OPTIONAL_HEADERS = ("招标代理",)


def parse_strict(xlsx_path: Path, sheet: str = "标讯明细") -> tuple[list[dict], list[str]]:
    """A 严格模式 xlsx→records。

    行为契约（owner 2026-09-13 定稿，基准样式 = 20260913 报告）：
      - 核心 16 列名精确匹配、顺序无关；缺列/重复列/未知列整体拒绝，不做同义词映射。
      - 「招标代理」为可选列，有则提取（owner 2026-09-13 增）。
      - 行字段全清洗：链接解 HYPERLINK 公式、日期归 ISO、金额转 float。
      - 状态列经 lead_status_normalize 归 5 态码。
      - 返回 (records, errors)：errors 列出被跳过的行及原因。

    Returns:
        records: 每项包含核心字段 + agency + link + status_code/status_matched
        errors: 错误清单（行号 + 原因），方便人工核修
    """
    import openpyxl
    errors: list[str] = []
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=False)
    ws = wb[sheet] if sheet in wb.sheetnames else wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    header_idx = next(
        (i for i, r in enumerate(rows) if r and any(str(c).strip() == STRICT_HEADERS[0] for c in r if c)),
        None,
    )
    if header_idx is None:
        raise SystemExit(f"❌ 严格模式：未找到表头行（缺「{STRICT_HEADERS[0]}」列）：{xlsx_path}")

    raw_header = [str(c).strip() if c is not None else "" for c in rows[header_idx]]
    # A 模式：核心 16 列按名字精确匹配（顺序无关），可选列有则取，未知列拒绝
    counts: dict[str, int] = {}
    for name in raw_header:
        if name:
            counts[name] = counts.get(name, 0) + 1
    missing = [h for h in STRICT_HEADERS if counts.get(h, 0) == 0]
    dup = [h for h in STRICT_HEADERS if counts.get(h, 0) > 1]
    allowed = set(STRICT_HEADERS) | set(OPTIONAL_HEADERS)
    unknown = [h for h in counts if h not in allowed]
    if missing or dup or unknown:
        parts = []
        if missing:
            parts.append("缺列: " + "、".join(missing))
        if dup:
            parts.append("重复列: " + "、".join(dup))
        if unknown:
            parts.append("未知列: " + "、".join(unknown))
        raise SystemExit(
            f"❌ 严格模式：表头校验失败 —— {xlsx_path}\n"
            f"   {'；'.join(parts)}\n"
            f"   实际表头：{raw_header}"
        )
    col = {name: raw_header.index(name) for name in raw_header if name}
    agency_idx = col.get("招标代理")

    def _cell(row, name):
        i = col.get(name)
        return row[i] if i is not None and i < len(row) else None

    records: list[dict] = []
    for row_num, r in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if r is None:
            continue
        row = {h: _cell(r, h) for h in STRICT_HEADERS}
        agency = str(_cell(r, "招标代理") or "").strip() if agency_idx is not None else ""

        title = str(row.get("项目名称") or "").strip()
        if not title:
            # 空行直接跳过，不计入错误
            if all(v in (None, "") for v in r):
                continue
            errors.append(f"行 {row_num}: 项目名称为空，已跳过")
            continue
        # 政策类排除
        type_text = str(row.get("类型") or "").strip()
        if any(k in type_text for k in SKIP_TYPE_KEYWORDS):
            continue

        link = extract_link(row.get("原文链接"))
        published_at = norm_date(row.get("发布时间"))
        amount_wan = norm_amount(row.get("金额(万元)"))
        deadline = str(row.get("截止/公示日期") or "").strip()
        status_text = str(row.get("状态") or "").strip()
        # 5 态归一（A 模式契约的一部分）
        if lead_status_normalize is not None and status_text:
            status_code, status_matched = lead_status_normalize.normalize(status_text)
        else:
            status_code, status_matched = ("unknown", "")

        records.append({
            "seq": row.get("序号"),
            "type": type_text,
            "title": title,
            "buyer": str(row.get("招标采购方") or "").strip(),
            "agency": agency,
            "summary": str(row.get("内容总结") or "").strip(),
            "service_type": str(row.get("服务类型") or "").strip(),
            "org_type": str(row.get("机构类型") or "").strip(),
            "published_at": published_at,
            "deadline": deadline,
            "amount_wan": amount_wan,
            "procurement": str(row.get("采购方式") or "").strip(),
            "status": status_text,
            "status_code": status_code,
            "status_matched": status_matched,
            "winner": str(row.get("中标方/候选人") or "").strip(),
            "link": link,
            "link_verified": str(row.get("链接核实") or "").strip(),
            "note": str(row.get("备注") or "").strip(),
        })

    return records, errors


def record_to_item(rec: dict, source: str) -> dict:
    """选择性填充：xlsx 全字段 → 看板 collection.sync 关键字段（v2.2 带生命周期四维）。

    刻意不填：score（评分归 scout 打分，人工确认归 lead.qualify）、region（xlsx 无此列）。
    phase/buyer_level/sub_industry/recommend 由 rules/lifecycle.py 确定性规则派生；
    优先级规则透明（投标/述标=P1，发标≥100万=P1，线索期≥500万=P1，其余=P2），
    人工可随时经 lead.patch / lead.qualify 覆盖。
    """
    key = f"{rec['title']}|{rec['buyer']}"
    lead_id = "xlsx-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    status = str(rec.get("status") or "").strip()
    winner = str(rec.get("winner") or "").strip()
    phase = lifecycle.classify_phase(str(rec.get("type") or ""), status, rec["title"], winner)
    level = lifecycle.buyer_level(str(rec.get("org_type") or ""), rec["buyer"])
    industry = lifecycle.sub_industry(rec["buyer"], str(rec.get("org_type") or ""))
    parts = [f"[{rec['type']}]" if rec["type"] else ""]
    if rec.get("summary"):
        parts.append(str(rec["summary"]).strip())
    if status:
        parts.append(f"状态：{status}")
    if winner:
        parts.append(f"中标方/候选人：{winner}")
    if rec.get("note"):
        parts.append(f"备注：{rec['note']}")
    item = {
        "lead_id": lead_id,
        "title": rec["title"],
        "buyer": rec["buyer"] or source,
        "industry": industry,
        "buyer_level": level,
        "sub_industry": industry,
        "phase": phase,
        "recommend": lifecycle.derive_priority(phase, rec["amount_wan"]),
        "amount": rec["amount_wan"],
        "deadline": rec["deadline"],
        "published_at": rec["published_at"],
        "link": rec["link"],
        "raw_keywords": " / ".join(
            x for x in (str(rec.get("service_type") or "").strip(),
                        str(rec.get("procurement") or "").strip()) if x
        ),
        "reason": " ｜ ".join(p for p in parts if p),
    }
    # A 严格模式：把 5 态信息透传给看板（collection.sync 需识别并写 status_* 列）
    if rec.get("status_code"):
        item["status_code"] = rec["status_code"]
        item["status_text"] = rec.get("status", "")
        item["status_matched"] = rec.get("status_matched", "")
    if rec.get("agency"):
        item["agency"] = rec["agency"]
    return item


def post_json(path: str, payload: dict, headers: dict | None = None) -> dict:
    """仅允许向本机看板白名单地址发请求（协议 + host 双重校验）。"""
    u = urlparse(KANBAN_ORIGIN + path)
    if u.scheme not in ("http", "https"):
        raise SystemExit(f"❌ 协议拒绝：{u.scheme}")
    hostport = f"{u.hostname}:{u.port}" if u.port else (u.hostname or "")
    if hostport not in KANBAN_HOSTS:
        raise SystemExit(f"❌ 目标不在白名单：{hostport}")
    req = urllib.request.Request(
        u.geturl(),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _selftest() -> int:
    """构造临时严格 xlsx，验证 parse_strict 全链路（顺序无关/可选列/拒绝面）。"""
    import tempfile
    try:
        import openpyxl
    except ImportError:
        print("❌ openpyxl 未安装，跳过自测（pip install openpyxl）")
        return 2

    fails = 0
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tf:
        tmp = Path(tf.name)

    # Case 1: 核心 16 列 + 「招标代理」可选列（基准样式 20260913）
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "标讯明细"
    ws.append(list(STRICT_HEADERS[:3]) + [STRICT_HEADERS[3], "招标代理"] + list(STRICT_HEADERS[4:]))
    ws.append([1, "招标公告", "测试项目A", "某银行", "某某招标代理有限公司", "测试总结", "等保测评", "金融机构",
               "2026-09-10", "2026-09-25", "100.5", "公开招标", "招标中", "",
               "https://example.com/a", "", ""])
    ws.append([2, "中标公告", "测试项目B", "某证券", "", "测试总结B", "安全运营", "金融机构",
               "2026-09-08", "", "200", "公开招标", "已中标", "测试公司B",
               "=HYPERLINK(\"https://example.com/b\",\"查看\")", "✓", ""])
    ws.append([3, "公示", "测试项目C", "某保险", "某某咨询代理", "测试总结C", "安全咨询", "金融机构",
               "2026-09-05", "", "50", "公开招标", "中标候选人公示", "",
               "", "", ""])
    wb.save(tmp)
    wb.close()

    recs, errs = parse_strict(tmp)
    print(f"✓ 严格模式 16+1 列解析：{len(recs)} 条，跳过 {len(errs)} 行")
    if len(recs) != 3:
        fails += 1
        print(f"   ✗ 期望 3 条，实际 {len(recs)}")
    if recs and recs[0]["status_code"] != "tender":
        fails += 1
        print(f"   ✗ 项目A 应判 tender，实际 {recs[0]['status_code']}")
    if recs and recs[1]["status_code"] != "awarded":
        fails += 1
        print(f"   ✗ 项目B 应判 awarded，实际 {recs[1]['status_code']}")
    if recs and recs[2]["status_code"] != "publicity":
        fails += 1
        print(f"   ✗ 项目C 应判 publicity，实际 {recs[2]['status_code']}")
    if recs and recs[0]["agency"] != "某某招标代理有限公司":
        fails += 1
        print(f"   ✗ 项目A 招标代理提取失败：{recs[0]['agency']!r}")
    if recs and recs[1]["agency"] != "":
        fails += 1
        print(f"   ✗ 项目B 招标代理应为空：{recs[1]['agency']!r}")
    if recs and recs[1]["link"] != "https://example.com/b":
        fails += 1
        print(f"   ✗ 项目B 链接解 HYPERLINK 失败：{recs[1]['link']!r}")

    # Case 2: 乱序表头（顺序无关，应通过）
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "标讯明细"
    shuffled = list(reversed(STRICT_HEADERS))
    ws.append(shuffled)
    ws.append(list(reversed([1, "招标公告", "测试项目D", "某银行", "测试总结", "等保测评", "金融机构",
                             "2026-09-10", "2026-09-25", "100.5", "公开招标", "招标中", "",
                             "https://example.com/d", "", ""])))
    wb.save(tmp)
    wb.close()
    recs2, _ = parse_strict(tmp)
    if len(recs2) != 1 or recs2[0]["status_code"] != "tender":
        fails += 1
        print(f"   ✗ 乱序表头应通过且判 tender：{len(recs2)} 条")
    else:
        print("✓ 乱序表头通过（顺序无关）")

    # Case 3: 缺列（期望拒绝）
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "标讯明细"
    ws.append(["序号", "类型", "项目名称", "招标采购方"])
    ws.append([1, "招标", "测试", "测试方"])
    wb.save(tmp)
    wb.close()
    try:
        parse_strict(tmp)
        fails += 1
        print("   ✗ 严格模式应拒绝缺列")
    except SystemExit as e:
        if "缺列" not in str(e):
            fails += 1
            print(f"   ✗ 拒绝原因未含「缺列」：{e}")
        else:
            print("✓ 严格模式拒绝缺列：符合预期")

    # Case 4: 未知列（期望拒绝，防静默吞新列）
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "标讯明细"
    ws.append(list(STRICT_HEADERS) + ["神秘新列"])
    ws.append(list([1, "招标公告", "测试", "测试方", "总结", "等保", "金融机构",
                    "2026-09-10", "", "100", "公开", "招标中", "", "", "", ""]) + ["x"])
    wb.save(tmp)
    wb.close()
    try:
        parse_strict(tmp)
        fails += 1
        print("   ✗ 严格模式应拒绝未知列")
    except SystemExit as e:
        if "未知列" not in str(e):
            fails += 1
            print(f"   ✗ 拒绝原因未含「未知列」：{e}")
        else:
            print("✓ 严格模式拒绝未知列：符合预期")

    # Case 5: 重复列（期望拒绝）
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "标讯明细"
    ws.append(list(STRICT_HEADERS) + ["项目名称"])
    wb.save(tmp)
    wb.close()
    try:
        parse_strict(tmp)
        fails += 1
        print("   ✗ 严格模式应拒绝重复列")
    except SystemExit as e:
        if "重复列" not in str(e):
            fails += 1
            print(f"   ✗ 拒绝原因未含「重复列」：{e}")
        else:
            print("✓ 严格模式拒绝重复列：符合预期")

    tmp.unlink(missing_ok=True)

    if fails:
        print(f"\n❌ selftest 失败 {fails}")
        return 1
    print(f"\n✅ selftest 通过")
    return 0


def main() -> None:
    # 先抓 --self-test（必须在 xlsx 必填前判；否则 argparse 会因缺位置参数退出）
    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test":
        sys.exit(_selftest())

    ap = argparse.ArgumentParser(description="标讯 xlsx 报告导入（xlsx→JSON→collection.sync）")
    ap.add_argument("xlsx", type=Path, help="标讯 xlsx 报告路径")
    ap.add_argument("--sheet", default="标讯明细", help="数据 sheet 名（默认 标讯明细）")
    ap.add_argument("--json-only", action="store_true", help="只转 JSON 不入库")
    ap.add_argument("--dry-run", action="store_true", help="打印前 3 条映射样例，不入库")
    ap.add_argument("--types", default="", help="按类型子集导入（逗号分隔，如 新增,招标公告；"
                                                 "匹配用「包含」语义，空=全部非政策）")
    ap.add_argument("--no-scan", action="store_true", help="入库后不触发时效扫描")
    ap.add_argument("--strict", action="store_true", default=True,
                    help="A 严格模式：16 列表头精确匹配 + 5态归一（默认开启；禁用用 --no-strict）")
    ap.add_argument("--no-strict", dest="strict", action="store_false",
                    help="退回兼容模式（按列序号映射，不做严格表头校验）")
    args = ap.parse_args()

    # B1.2（2026-09-26）：xlsx 脱敏机检——此前 xlsx 导入完全绕过机检（buyer/金额最密载体）。
    # 扫描 sharedStrings + sheet XML，命中即整体拒绝（宁可拦，不可漏）；CLI 与看板 API 路径同享。
    if args.xlsx.exists():
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import desensitize as _ds
        xhits = _ds.scan_xlsx(args.xlsx)
        if xhits:
            print(f"⛔ 脱敏机检命中 {len(xhits)} 处（L3 红线），xlsx 导入拒绝：")
            for h in xhits[:10]:
                print(f"   · [{h['type']}] {h['masked']} @ {h.get('part', '?')}")
            if len(xhits) > 10:
                print(f"   · ... 还有 {len(xhits) - 10} 处")
            raise SystemExit(1)

    if not args.xlsx.exists():
        # 源 xlsx 被外部工具轮转清理时，从 JSON 存档复算（①步产物可复算的意义所在）
        archive = IMPORTS_DIR / f"{args.xlsx.stem}.json"
        if not archive.exists():
            raise SystemExit(f"❌ 文件不存在：{args.xlsx}（也无存档 {archive}）")
        print(f"⚠ 源 xlsx 不在，从存档复算：{archive}")
        records = json.loads(archive.read_text(encoding="utf-8"))["records"]
        strict_errors: list[str] = []
    elif args.strict:
        records, strict_errors = parse_strict(args.xlsx, args.sheet)
        if strict_errors:
            print(f"⚠ 严格模式跳过 {len(strict_errors)} 行：")
            for e in strict_errors[:10]:
                print(f"   · {e}")
            if len(strict_errors) > 10:
                print(f"   · ... 还有 {len(strict_errors) - 10} 行")
    else:
        records = xlsx_to_records(args.xlsx, args.sheet)
        strict_errors = []

    skipped_policy = [r for r in records if any(k in r["type"] for k in SKIP_TYPE_KEYWORDS)]
    wanted = [r for r in records if r not in skipped_policy]
    if args.types:
        keys = tuple(t.strip() for t in args.types.split(",") if t.strip())
        wanted = [r for r in wanted if any(k in r["type"] for k in keys)]
    no_link = [r for r in wanted if not r["link"]]
    items = [record_to_item(r, source=f"xlsx:{args.xlsx.stem}") for r in wanted]

    # ① JSON 中间产物落盘（真实层可复算存档；从存档复算时原样保留，不刷新时间戳）
    if not args.xlsx.exists():
        json_path = IMPORTS_DIR / f"{args.xlsx.stem}.json"
    else:
        IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
        json_path = IMPORTS_DIR / f"{args.xlsx.stem}.json"
        json_path.write_text(
            json.dumps({"report": args.xlsx.name, "imported_at": datetime.now().isoformat(timespec="seconds"),
                        "records": records}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"① xlsx→JSON 完成：{len(records)} 条记录 → {json_path}")
    print(f"   跳过政策类 {len(skipped_policy)} 条；缺原文链接 {len(no_link)} 条（照导，link 留空不挡）；本次待入 {len(items)} 条")

    if args.json_only:
        return
    if args.dry_run:
        for it in items[:3]:
            print(json.dumps(it, ensure_ascii=False, indent=2))
        return

    # ② collection.sync 幂等入库（mode=upsert：已有 lead_id 刷新报告可推导字段，
    #    人工 sales_owner / reviewed 定级永不回盖；审计+SSE 全走看板命令管道）
    if not items:
        print("② 无可导入条目，跳过入库")
        return
    file_hash = hashlib.sha256(json_path.read_bytes()).hexdigest()
    resp = post_json("/api/v1/commands", {
        "commandId": "collection.sync",
        "params": {"items": items, "source": f"xlsx-import:{args.xlsx.stem}",
                   "run_id": f"xlsx_{file_hash[:12]}", "mode": "upsert",
                   "payload_hash": file_hash, "channel_name": "xlsx-report"},
    }, headers={"Idempotency-Key": f"xlsx-import-{file_hash}",
                "Payload-Hash": file_hash, "X-Agent-Id": "import-xlsx-leads"})
    print(f"② collection.sync(upsert) → {resp}")

    # ③ 时效扫描：发布超期自动进关闭区（v0.3.2 关闭区纪律）
    if not args.no_scan:
        scan = post_json("/api/v1/leads/scan-freshness", {})
        print(f"③ 时效扫描：扫描 {scan.get('scanned')} · 关闭区 {len(scan.get('expired', []))} · 老化 {len(scan.get('aging', []))}")


if __name__ == "__main__":
    sys.exit(main())
