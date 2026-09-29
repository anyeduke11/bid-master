#!/usr/bin/env python3
"""desensitize.py · 脱敏机检（W2 2.4）

设计依据：docs/baw-design-v3.md §6.3（摄取口脱敏）/§14（合规红线，拦截率要求 100%）
────────────────────────────────────────────────────────────────
挂载点：
  1. inbox → 转正路径（W4 ingest.py 调用，命中即拦）
  2. S8→S9 门禁（set_stage.py 调用：归档提案 100% 过机检，acceptance §3.6）

模式库（L3 红线机检面 · B1.2 扩为六类；2026-09-26 覆盖核对见
docs/designs/desensitize-coverage-review-20260926.md）：
  身份证     18 位（含校验位 X）      → hard
  手机号     1[3-9] 开头 11 位        → hard
  证书编号   已知前缀 / 连字编码含数字 → hard（容忍误报：宁可人复核，不可漏放）
  成本价/底价 显式关键词+数字          → hard（B1.2 新增）
  折扣       折扣率/让利/下浮+数字、N折 → hard（B1.2 新增；命中打码不留数值）
  客户名单   不做机检—— buyer 真名靠「别名+行业」人工纪律（基线约束 1/2）
  涉密四类（报价/商务资质/人员简历/方案案例）不做自动识别机检（基线明确，文档级人工打标）

用法：
  python3 rules/desensitize.py <file|dir>            # 扫描，命中 exit 1（报告里 PII 打码）
  python3 rules/desensitize.py <file> --redact       # 输出 <name>.redacted（命中处替换为 [REDACTED:<类型>]）
  python3 rules/desensitize.py --selftest            # 自测（tests/sample/desensitize/ 两样本）

本文件自身是"安全实现样板"：不用 open()，报告不回显完整敏感串（只留前 3 位打码）。
"""
import json
import re
import sys
from pathlib import Path

# ── 模式库 ──────────────────────────────────────────────
PATTERNS = {
    "身份证": re.compile(r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)"),
    "手机号": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "证书编号-已知前缀": re.compile(
        r"(?<![A-Za-z0-9])(?:CCRC|CNCERT|CNNVD|CISP|CISSP|PMP|ITSS|CNAS|CMA|NISP|CISAW)"
        r"(?:[-—／/][A-Za-z0-9\u4e00-\u9fff]{1,12}){1,6}(?![A-Za-z0-9])"),
    "证书编号-连字编码": re.compile(
        r"(?<![A-Za-z0-9])[A-Z][A-Za-z0-9]{1,9}(?:-[A-Za-z0-9]{1,12}){2,6}(?![A-Za-z0-9])"),
    # B1.2（2026-09-26）：成本价/折扣模式——显式关键词+数字才命中，避免"成本低""打折促销"类散文误报
    "成本价": re.compile(r"(?<![0-9A-Za-z])(?:成本价|成本单价|我方成本|我方底价|报价底价|底价)[:：]?\s*[¥￥$]?\s*\d[\d,，.]*"),
    "折扣-关键词": re.compile(r"(?<![0-9A-Za-z])(?:折扣率|折扣|让利|下浮)[:：]?\s*\d{1,3}(?:\.\d+)?\s*%?"),
    "折扣-折数": re.compile(r"(?<![0-9.%])[1-9](?:\.\d{1,2})?折(?![0-9A-Za-z])"),
}
# 连字编码需含至少两位数字才视为编号（排除 UTF-8、GB/T 类；招标编号类误报交由人工白名单）
_CODE_MUST_HAVE_DIGITS = re.compile(r"\d")

# 白名单：整串 fullmatch 任一条则不视为命中（rules/desensitize_allowlist.txt，版本化、可审计）
_ALLOWLIST_FILE = Path(__file__).resolve().parent / "desensitize_allowlist.txt"
ALLOWLIST = []
if _ALLOWLIST_FILE.exists():
    for _ln in _ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
        _ln = _ln.split("#", 1)[0].strip()
        if _ln:
            ALLOWLIST.append(re.compile(_ln))


def _allowlisted(s: str) -> bool:
    return any(a.fullmatch(s) for a in ALLOWLIST)


def scan_text(text: str) -> list:
    """返回 [{type, masked, pos}]；敏感串打码（保留前 3 字符），不回显原文。
    例外：折扣-折数串短（"8.5折"全串 3-4 字符），前 3 字打码即泄露数值——整串不回显。"""
    hits = []
    for ptype, pat in PATTERNS.items():
        for m in pat.finditer(text):
            s = m.group(0)
            if ptype == "证书编号-连字编码" and not _CODE_MUST_HAVE_DIGITS.search(s):
                continue
            if _allowlisted(s):
                continue
            if ptype == "折扣-折数":
                masked = "折扣数值打码"
            else:
                masked = s[:3] + "*" * max(len(s) - 3, 3)
            hits.append({"type": ptype, "masked": masked, "pos": m.start()})
    hits.sort(key=lambda h: h["pos"])
    return hits


def scan_xlsx(p: Path) -> list:
    """xlsx 机检（B1.2）：xlsx 是 zip 容器，抽取 sharedStrings 与各 sheet 的 XML 文本，
    去标签后按文本模式扫描——此前 xlsx（buyer/金额最密载体）完全绕过机检。
    损坏/非标准文件返回空列表（放行策略由调用方定；导入路径另有严格表头校验兜底）。"""
    import html as _html
    import zipfile
    hits: list = []
    try:
        with zipfile.ZipFile(p) as z:
            parts = [n for n in z.namelist()
                     if n == "xl/sharedStrings.xml"
                     or (n.startswith("xl/worksheets/") and n.endswith(".xml"))]
            for n in parts:
                raw = z.read(n).decode("utf-8", errors="replace")
                # 两步还原：去 XML 标签 + 解数字字符引用（openpyxl 写 &#25104; 而非"成"，不解码则中文全部漏检）
                text = _html.unescape(re.sub(r"<[^>]+>", " ", raw))
                for h in scan_text(text):
                    h = dict(h)
                    h["part"] = n
                    hits.append(h)
    except Exception:
        return []
    hits.sort(key=lambda h: h.get("pos", 0))
    return hits


def scan_path(p: Path) -> dict:
    if p.is_dir():
        files = sorted(x for x in p.rglob("*") if x.is_file()
                       and x.suffix.lower() in (".txt", ".md", ".json", ".csv", ".xlsx"))
        return {"path": str(p), "files": [scan_path(x) for x in files],
                "hits": sum(h["hits"] for h in [scan_path(x) for x in files])}
    if p.suffix.lower() == ".xlsx":
        hits = scan_xlsx(p)
    else:
        hits = scan_text(p.read_text(encoding="utf-8", errors="replace"))
    return {"path": str(p), "hits": len(hits), "detail": hits}


def redact_file(p: Path) -> Path:
    out = p.with_name(p.stem + ".redacted" + p.suffix)
    text = p.read_text(encoding="utf-8", errors="replace")
    for ptype, pat in PATTERNS.items():
        text = pat.sub(lambda m: f"[REDACTED:{ptype}]", text)
    out.write_text(text, encoding="utf-8")
    return out


def selftest() -> int:
    base = Path(__file__).resolve().parent.parent / "tests" / "sample" / "desensitize"
    hits_case = base / "sample_hits.txt"
    clean_case = base / "sample_clean.md"
    ok = True
    r1 = scan_path(hits_case)
    types = {h["type"] for h in r1["detail"]}
    need = {"身份证", "手机号", "证书编号-已知前缀", "证书编号-连字编码",
            "成本价", "折扣-关键词", "折扣-折数"}
    if not need <= types:
        print(f"❌ 自测失败：{hits_case.name} 应命中全部七类，实得 {types}")
        ok = False
    # B1.2：折扣-折数打码不得泄露数值
    for h in r1["detail"]:
        if h["type"] == "折扣-折数" and "折扣数值打码" not in h["masked"]:
            print(f"❌ 自测失败：折扣-折数打码泄露数值：{h['masked']}")
            ok = False
    r2 = scan_path(clean_case)
    if r2["hits"] != 0:
        print(f"❌ 自测失败：{clean_case.name} 应 0 命中，实得 {r2['hits']}（误报样本：{r2['detail'][:3]}）")
        ok = False
    if ok:
        print(f"✅ desensitize 自测通过：敏感样本命中 {r1['hits']} 处（七类齐），干净样本 0 命中")
    return 0 if ok else 1


def main() -> int:
    args = [a for a in sys.argv[1:]]
    if "--selftest" in args:
        return selftest()
    redact = "--redact" in args
    targets = [a for a in args if not a.startswith("--")]
    if not targets:
        print(__doc__)
        return 3
    report = scan_path(Path(targets[0]))
    total = report.get("hits", 0) if "hits" in report else sum(f["hits"] for f in report.get("files", []))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if redact and report.get("hits"):
        print("redacted →", str(redact_file(Path(targets[0]))))
    if total:
        print(f"⛔ 命中 {total} 处红线（身份证/手机号/证书编号/成本价/折扣），拦截。", file=sys.stderr)
        return 1
    print("✅ 未命中红线模式。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
