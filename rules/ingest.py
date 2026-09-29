#!/usr/bin/env python3
"""ingest.py · 外部工具收割（W4 4.2）

设计依据：docs/baw-design-v3.md §12（收割与冲突规则）、§14（脱敏挂载）
────────────────────────────────────────────────────────────────
流程：扫源目录增量 → 指纹判重（registry.json）→ 类型识别 → 拷贝进
      ~/.bidmaster/inbox/<来源>/<批次>/（追加式，永不覆盖）→ 脱敏机检 → 命中入 rejects/（带原因）
冲突规则：flock 单实例；外部目录只读；单一写者=本脚本。

类型识别（按内容/命名）：
  tender      招标文件全文（txt/md 且含 [P#] 页锚或"招标"类关键词）
  audit-data  结构化审计数据（audit_data.json）
  checklist   审计/评审核对单（md 且文件名含 核对单|评审|审计）
  lead-table  xlsx 线索表
  doc         其他文档（md/txt 兜底）

用法：
  python3 rules/ingest.py --source <dir> [--dry-run] [--max N] [--types tender,lead-table]
  python3 rules/ingest.py --all [--types tender,lead-table]   # 全部源实收（DEV-0081 起）
  python3 rules/ingest.py --all-dry                            # 全部源 dry-run 统计（不拷贝）
说明：--types 白名单过滤（classify 后不在名单的类型跳过）——外部工具目录 9 成是
      通用文档（doc），默认建议只收 tender/lead-table（owner 2026-09-26 批准）。
      trae 源已移除（~/.trae/workspace 不存在，每晚空报；如需恢复在 SOURCES 加回即可）。
"""
import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

DATA_ROOT = Path.home() / ".bidmaster"
INBOX = DATA_ROOT / "inbox"
REGISTRY = INBOX / "registry.json"
LOCK = INBOX / ".ingest.lock"
SOURCES = {
    "lingxi-claw": Path.home() / "Documents" / "lingxi-claw",
    "workbuddy": Path.home() / "WorkBuddy",
}
SCAN_SUFFIX = (".txt", ".md", ".json", ".xlsx")
SKIP_DIRS = {".rundata", "node_modules", "__pycache__", ".git", "skills", "output", "bid_images"}
MAX_SIZE = 20 * 1024 * 1024  # 20MB 上限，防大文件误收


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _fp(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def classify(p: Path) -> str:
    name = p.name.lower()
    if name.endswith(".xlsx"):
        return "lead-table"
    if name == "audit_data.json":
        return "audit-data"
    if p.suffix == ".json":
        return "doc"
    if re.search(r"核对单|评审|审计", p.name):
        return "checklist"
    try:
        head = p.read_text(encoding="utf-8", errors="ignore")[:4000]
    except Exception:
        return "doc"
    if re.search(r"\[P\d+\]|招标|采购|投标邀请|废标", head):
        return "tender"
    return "doc"


def load_registry() -> dict:
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {}


def save_registry(reg: dict) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, REGISTRY)


def scan_source(src: Path, limit: int | None):
    files = []
    if not src.exists():
        return files
    for p in sorted(src.rglob("*")):
        if limit is not None and len(files) >= limit:
            break
        if p.is_file() and p.suffix.lower() in SCAN_SUFFIX and p.stat().st_size <= MAX_SIZE:
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            files.append(p)
    return files


def ingest(source: str, dry: bool, limit: int | None, types: set | None = None) -> int:
    src = SOURCES.get(source)
    if not src or not src.exists():
        print(f"源不存在或未配置：{source} → {src}")
        return 3
    reg = load_registry()
    batch = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest_dir = INBOX / source / batch
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import desensitize as _ds
    n_new = n_dup = n_reject = n_skip_type = 0
    for p in scan_source(src, limit):
        rel_type = classify(p)
        if types is not None and rel_type not in types:
            n_skip_type += 1
            continue
        fp = _fp(p)
        if fp in reg:
            n_dup += 1
            continue
        safe_name = re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", p.name)  # 落盘名白名单化，防路径意外
        dest = dest_dir / rel_type / safe_name
        base_real = os.path.realpath(str(dest_dir))
        dest_real = os.path.realpath(os.path.normpath(str(dest)))
        if ".." in p.name or not dest_real.startswith(base_real + os.sep):
            print(f"⚠ 跳过异常路径：{p}")
            continue
        hits = []
        # B1.2（2026-09-26）：xlsx 纳检 + 去 200KB 截断——xlsx 是 buyer/金额最密载体，此前完全绕过机检；
        # 文本类全量扫描（MAX_SIZE 20MB 上限已由 scan_source 保证，头部扫描会漏检长文件尾部红线）
        if p.suffix.lower() == ".xlsx":
            hits = _ds.scan_xlsx(p)
        elif p.suffix.lower() in (".txt", ".md", ".json"):
            try:
                hits = _ds.scan_text(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                hits = []
        if dry:
            print(f"[dry] {rel_type:10s} {'REJECT' if hits else 'inbox '} {p.name}")
            n_new += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        if hits:
            rej = INBOX / source / "rejects" / f"{batch}.jsonl"
            rej.parent.mkdir(parents=True, exist_ok=True)
            prev = rej.read_text(encoding="utf-8") if rej.exists() else ""
            rej.write_text(prev + json.dumps({"file": str(p), "dest": str(dest_real),
                                              "hits": [{"type": h["type"], "masked": h["masked"]} for h in hits],
                                              "reason": "脱敏机检命中", "ts": _now()}, ensure_ascii=False) + "\n",
                           encoding="utf-8")
            n_reject += 1
        reg[fp] = {"source": source, "batch": batch, "orig": str(p),
                   "dest": str(dest_real), "type": rel_type, "ingested_at": _now(),
                   "desens": "hits" if hits else "clean"}
        n_new += 1
    if not dry:
        save_registry(reg)
    print(f"ingest[{source}] batch={batch}：新增 {n_new}（其中脱敏拦截 {n_reject}）/ 重复跳过 {n_dup}"
          + (f" / 类型过滤跳过 {n_skip_type}" if types is not None else "")
          + ("（dry-run，未落盘）" if dry else ""))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="外部工具收割（flock + 指纹幂等 + 类型识别 + 脱敏）")
    ap.add_argument("--source", choices=sorted(SOURCES))
    ap.add_argument("--all", action="store_true", help="全部源实收（DEV-0081 起为默认工作模式）")
    ap.add_argument("--all-dry", action="store_true", help="全部源 dry-run 统计（不拷贝）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--types", default=None,
                    help="类型白名单（逗号分隔，如 tender,lead-table）；缺省收全部类型")
    ap.add_argument("--max", type=int, default=None, help="本次最多处理文件数")
    a = ap.parse_args()
    types = {t.strip() for t in a.types.split(",") if t.strip()} if a.types else None
    INBOX.mkdir(parents=True, exist_ok=True)
    # flock 单实例摄取（设计 §12.2）：os.open 原生 fd
    lock_fd = os.open(str(LOCK), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(lock_fd)
        print("⛔ 另一个 ingest 实例在运行（flock 单实例）。")
        return 1
    try:
        if a.all or a.all_dry:
            rc = 0
            for s in SOURCES:
                rc = rc or ingest(s, dry=a.all_dry and not a.all, limit=a.max, types=types)
            return rc
        if not a.source:
            ap.print_help()
            return 3
        return ingest(a.source, dry=a.dry_run, limit=a.max, types=types)
    finally:
        os.close(lock_fd)


if __name__ == "__main__":
    sys.exit(main())
