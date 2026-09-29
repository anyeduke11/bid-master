#!/usr/bin/env python3
"""kb_init.py · kb 半自动初始化（W2 2.3）

设计依据：docs/baw-design-v3.md §6（kb 三层/存量初始化）
────────────────────────────────────────────────────────────────
动作：
  1. raw 归档：三标（某证券通信机构/某证券交易所/东莞银行）源文件 → kb/raw/past-bids/<bid_id>/（规范化名，原件不改动）
  2. index v1（全部 status=draft 待人工复核）：
     - bids_history：三标各一条（阶段/结果待人工补）
     - certs：从某证券通信机构投标文本抽证照名称（**编号不录入——L3 红线**；有效期待人工核）
     - people：占位骨架（人员信息须人工补，防 PII 直接入库）
     - cases：占位指针（业绩章节原文位置，待人工拆条）

安全：index 中已有非 draft 条目时拒绝重写（保护人工确认成果），--force 才覆盖 draft。
用法：python3 rules/kb_init.py [--force]
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KB = REPO / "kb"
RAW = KB / "raw" / "past-bids"
NOW = datetime.now().astimezone().isoformat(timespec="seconds")

SOURCES = {
    "2026-GOLD-jishu": {
        "batch": Path.home() / "Documents/lingxi-claw/20260623-15-53-04-363",
        "alias": "某证券通信机构", "project": "安全技术支持服务采购",
        "stage_reached": "S3(阶段0-3)", "result": None, "sensitivity": "L2",
        "files": {"tender_full_text.txt": "tender.txt", "bid_full_text.txt": "bid_full.txt",
                  "bid_一_资格审查文件.txt": "bid_1_qualification.txt", "bid_二_商务标.txt": "bid_2_business.txt",
                  "bid_三_技术标.txt": "bid_3_technical.txt", "bid_四_价格标.txt": "bid_4_price.txt",
                  "安全技术支持服务采购_招标审计核对单.md": "audit_checklist.md",
                  "安全技术支持服务采购_投标文件评审报告.md": "bid_review.md",
                  "audit_data.json": "audit_data.json"},
        "cert_scan_files": ["bid_1_qualification.txt", "bid_3_technical.txt"],
        "secondary": False,
    },
    "2026-szse-zhongbao": {
        "batch": Path.home() / "Documents/lingxi-claw/20260618-18-58-47-877",
        "alias": "某证券交易所", "project": "网络安全重保协防服务采购",
        "stage_reached": "S2(阶段0-2)", "result": None, "sensitivity": "L2",
        "files": {"招标文件_全文.txt": "tender.txt",
                  "网络安全重保协防服务采购_招标审计核对单.md": "audit_checklist.md"},
        "cert_scan_files": [], "secondary": False,
    },
    "2026-dgbank-attack": {
        "batch": Path.home() / "Documents/lingxi-claw/20260717-18-32-34-984",
        "alias": "东莞银行", "project": "网络攻防演习保障项目",
        "stage_reached": "S2(阶段0-2,二手源)", "result": None, "sensitivity": "L2",
        "files": {"audit_data.json": "audit_data.json"},
        "cert_scan_files": [], "secondary": True,
    },
}

CERT_KEYWORD = re.compile(r"(CCRC|CNCERT|CNNVD|CISP|CISSP|PMP|ITSS|CNAS|CMA|NISP|CISAW|信息安全服务资质|应急服务支撑单位|漏洞管理|风险评估资质|应急处理服务资质|网络安全等级测评)")
_CODE_TOKEN = re.compile(r"[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]{1,12}){1,6}")


def _sha256(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def _clean_cert_name(line: str) -> str:
    """抽证照名称并剥离编号类 token（L3：编号不录入 index）。
    三道剥离：连字编码 / "编号：xxxx" 段 / 5 位以上长数字串；清洗后仍须含证照关键词且长度合理。"""
    s = _CODE_TOKEN.sub("", line)
    s = re.sub(r"编号[:：]?\s*[A-Za-z0-9]{4,}", "", s)
    s = re.sub(r"\d{5,}", "", s)
    s = re.sub(r"\s+", " ", s).strip(" 　-—·、;；,，:：")
    if not (4 <= len(s) <= 40):
        return ""
    if not CERT_KEYWORD.search(s):
        return ""
    return s


def archive_raw() -> dict:
    copied = {}
    for bid_id, src in SOURCES.items():
        if not src["batch"].exists():
            print(f"⚠ 跳过 {bid_id}：批次不存在 {src['batch']}")
            continue
        dest_dir = RAW / bid_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        fmap = {}
        for orig, norm in src["files"].items():
            s, d = src["batch"] / orig, dest_dir / norm
            if not s.exists():
                continue
            if not d.exists() or d.stat().st_size != s.stat().st_size:
                shutil.copy2(s, d)   # 归档副本；原件永不改动
            fmap[norm] = {"path": f"kb/raw/past-bids/{bid_id}/{norm}",
                          "fingerprint": _sha256(d), "bytes": d.stat().st_size}
        copied[bid_id] = fmap
    return copied


def seed_indexes(raw: dict) -> bool:
    # 保护人工确认成果：存在非 draft 条目则拒绝
    for name in ("bids_history", "certs", "people", "cases"):
        p = KB / "index" / f"{name}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        confirmed = [i for i in d.get("items", []) if not str(i.get("status", "draft")).startswith("draft")]
        if confirmed and not ARGS.force:
            print(f"❌ {name}.json 已有人工确认条目，拒绝重写（--force 才覆盖 draft 区域）")
            return False

    # bids_history：三标各一条
    items = []
    for bid_id, src in SOURCES.items():
        if bid_id not in raw:
            continue
        items.append({
            "id": bid_id, "client_alias": src["alias"], "project": src["project"],
            "stage_reached": src["stage_reached"], "result": src["result"],
            "lessons": [], "secondary": src["secondary"],
            "file": f"kb/raw/past-bids/{bid_id}/", "fingerprint": _sha256(RAW / bid_id / "audit_data.json") if (RAW / bid_id / "audit_data.json").exists() else None,
            "sensitivity": src["sensitivity"], "status": "draft 待人工复核（补 result/lessons）", "updated_at": NOW})
    _write_index("bids_history", items, "三标历史（源自 lingxi-claw 批次，2026-09-10 半自动初始化）")

    # certs：某证券通信机构投标文本抽名称（编号不录入）
    certs, seen = [], {}
    GOLD = SOURCES["2026-GOLD-jishu"]
    for fname in GOLD["cert_scan_files"]:
        f = RAW / "2026-GOLD-jishu" / fname
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if not CERT_KEYWORD.search(line):
                continue
            m = re.match(r"\[P(\d+)\]\([^)]*\)\s*(.*)", line)
            page, body = (f"P{m.group(1)}", m.group(2)) if m else (None, line)
            name = _clean_cert_name(body)
            if not name:
                continue
            key = name.upper()
            if key in seen:
                seen[key]["page_hits"].append(page)
                continue
            entry = {"id": f"CERT-{len(certs)+1:03d}", "name": name, "level": None,
                     "issuer": None, "valid_from": None, "valid_until": None,
                     "cert_number": None, "page": page, "page_hits": [page] if page else [],
                     "note": "编号属 L3 不录入（设计§14）；等级/有效期待人工对照原件核",
                     "file": f"kb/raw/past-bids/2026-GOLD-jishu/{fname}",
                     "fingerprint": _sha256(f), "sensitivity": "L2",
                     "status": "draft 待人工复核", "updated_at": NOW}
            seen[key] = entry
            certs.append(entry)
    _write_index("certs", certs, "公司级证照（金标准演练标投标文件抽取，名称级；编号 L3 未录入）")

    # people：占位骨架（防 PII 直接入库，须人工补）
    people = [{
        "id": "P-001", "name_alias": "项目经理（金标准演练标，真名待人工录入）", "role": "项目经理",
        "certs": ["CISP(待核)", "PMP(待核)"], "years": None,
        "file": "kb/raw/past-bids/2026-GOLD-jishu/bid_3_technical.txt", "fingerprint": _sha256(RAW / "2026-GOLD-jishu" / "bid_3_technical.txt"),
        "sensitivity": "L2", "status": "draft 待人工复核（补真名/年限——真名属个人信息，入库前确认必要性）", "updated_at": NOW}]
    _write_index("people", people, "人员骨架（半自动只建指针，人工补齐）")

    # cases：占位指针（业绩章节待人工拆条）
    cases = [{
        "id": "CASE-001", "client_alias": "某证券通信机构", "industry": "证券通信", "year": 2026,
        "scene": ["安全技术支持"], "amount_band": None,
        "file": "kb/raw/past-bids/2026-GOLD-jishu/bid_2_business.txt",
        "fingerprint": _sha256(RAW / "2026-GOLD-jishu" / "bid_2_business.txt"),
        "slices": [], "sensitivity": "L2",
        "status": "draft 待人工拆条（商务标业绩章节→逐案例切片）", "updated_at": NOW}]
    _write_index("cases", cases, "业绩案例占位（待人工从商务标拆条）")
    return True


def _write_index(name: str, items: list, desc: str) -> None:
    p = KB / "index" / f"{name}.json"
    old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    out = {"_meta": {**(old.get("_meta") or {}), "version": old.get("_meta", {}).get("version", 1),
                     "desc": desc, "updated_at": NOW,
                     "rule": "只存元数据与文件指针；证件号/证书编号/成本价等 L3 信息不落索引（设计§14）"},
           "items": items}
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ {name}.json：{len(items)} 条（draft）")


ARGS = None


def main() -> int:
    global ARGS
    ap = argparse.ArgumentParser(description="kb 半自动初始化（raw 归档 + index v1 draft）")
    ap.add_argument("--force", action="store_true", help="draft 区域允许重生成（人工确认条目仍受保护）")
    ARGS = ap.parse_args()
    raw = archive_raw()
    n = sum(len(v) for v in raw.values())
    print(f"raw 归档：{len(raw)} 标 / {n} 文件 → kb/raw/past-bids/")
    if not seed_indexes(raw):
        return 1
    print("完成：index 全部为 draft，人工复核（status→confirmed）后即 kb v1。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
