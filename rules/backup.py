#!/usr/bin/env python3
"""backup.py · 真实层/观察层在线备份（B1.4 · 2026-09-26）

背景：truth.db 是全系统唯一不可重建的资产（bids.jsonl 回退路径已随 v1.0 退役）；
基线约束 7 承诺"每周手工快照"——手工的事没人做，故进调度（scheduler backup 任务，每周 cadence）。
D3 拍板（2026-09-26）：app.db 是 leads 权威（含人工 qualify/patch/promote 不可再生判断）→ 同批备份。

产出 ~/.bidmaster/backup/db/<YYYY-MM-DD>/：
  truth.db / app.db      sqlite3 backup API（在线安全，WAL 兼容，不停服务）
  ingest-registry.json   收割判重状态（丢了会全量重收）
  manifest.json          {file, bytes, sha256} 清单
滚动保留最近 KEEP=4 份；当日重跑幂等（已存在则刷新 manifest 后退出）。

用法：python3 rules/backup.py        # scheduler 每周调用；手动随时可跑
"""
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DATA_ROOT = Path(os.environ.get("BIDMASTER_HOME") or (Path.home() / ".bidmaster"))
BACKUP_ROOT = DATA_ROOT / "backup" / "db"
INBOX_REGISTRY = DATA_ROOT / "inbox" / "registry.json"
KEEP = 4


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _backup_sqlite(src: Path, dest: Path) -> None:
    """在线备份（sqlite3 backup API）：对 WAL 库安全，不阻塞并发读写。"""
    s = sqlite3.connect(str(src))
    d = sqlite3.connect(str(dest))
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


def main() -> int:
    date_tag = datetime.now().strftime("%Y-%m-%d")
    dest_dir = BACKUP_ROOT / date_tag
    existed = dest_dir.exists()
    dest_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    for name in ("truth.db", "app.db"):
        src = DATA_ROOT / name
        if not src.exists():
            print(f"⚠ 源库不存在，跳过：{src}")
            continue
        dest = dest_dir / name
        _backup_sqlite(src, dest)
        entries.append({"file": name, "bytes": dest.stat().st_size, "sha256": _sha256(dest)})
    if INBOX_REGISTRY.exists():
        dest = dest_dir / "ingest-registry.json"
        shutil.copyfile(INBOX_REGISTRY, dest)
        entries.append({"file": "ingest-registry.json",
                        "bytes": dest.stat().st_size, "sha256": _sha256(dest)})

    manifest = {"date": date_tag, "created_at": datetime.now().isoformat(timespec="seconds"),
                "entries": entries}
    (dest_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # 滚动清理：按目录名（日期序）保留最近 KEEP 份
    dirs = sorted(d for d in BACKUP_ROOT.iterdir() if d.is_dir())
    for old in dirs[:-KEEP]:
        shutil.rmtree(old, ignore_errors=True)
        print(f"🗑 滚动清理：{old.name}")

    total_mb = sum(e["bytes"] for e in entries) / 1048576
    print(f"✅ 备份完成：{dest_dir}（{len(entries)} 文件 {total_mb:.1f} MB"
          f"{'，当日重跑已刷新' if existed else ''}；保留 {min(len(dirs), KEEP)} 份滚动）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
