#!/usr/bin/env python3
"""lead_status_check.py · 标讯历史状态复核机（owner 2026-09-13）

用途：定时（cron_baw.sh lead-status-check，11:00 / 17:00）复查所有带原文链接的 lead，
      拉详情页文本→剥标签→走 lead_status_normalize 归 5 态，
      侦测状态转移 → 更新 leads.status_code/text/checked_at → 写 events 留痕。
      终态（awarded/delivered/closed）不复核；unknown 写反馈事件；失败退避（fail_count>=5 出队）。

CLI：
  python3 rules/lead_status_check.py --limit 50            # 默认批 50
  python3 rules/lead_status_check.py --lead <lead_id>      # 单条复核（手工触发）
  python3 rules/lead_status_check.py --dry-run             # 只打印不写库
  python3 rules/lead_status_check.py --self-test           # 自测（构造假 lead + mock fetch）
  python3 rules/lead_status_check.py --report-unknown [N]  # 近 N 天 unknown 聚类
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "rules"))

import safe_fetch  # noqa: E402  共享 SSRF 防护
import lead_status_normalize as lsn  # noqa: E402  5态状态机

DB_PATH = Path(os.environ.get("BIDMASTER_HOME") or (Path.home() / ".bidmaster")) / "app.db"
DEFAULT_LIMIT = 50
MIN_INTERVAL_HOURS = 4
FETCH_FAIL_THRESHOLD = 5  # 失败 >= 5 次出队（方案3 失败退避）


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _strip_html(text: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _fetch_status_text(url):
    body, final_url = safe_fetch.fetch(url)
    for enc in ("utf-8", "gbk", "utf-8"):
        try:
            raw = body.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raw = body.decode("utf-8", errors="replace")
    m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    title = re.sub(r"\s+", " ", m.group(1)).strip()[:200] if m else ""
    body_text = _strip_html(raw)
    combined = (title + " " + body_text[:4000]).strip()
    return combined, final_url


def _iter_candidates(conn, lead_id, limit, min_interval_hours):
    """取待复核 lead：
    - 终态（awarded/delivered/closed）直接排除（方案2）
    - 非终态按状态码分频：publicity 12h，tender/unknown 24h
    - fetch_fail_count >= 5 出队（方案3 失败退避）
    """
    if lead_id:
        row = conn.execute(
            "SELECT id, lead_id, title, buyer, link, status_code, status_text, "
            "status_checked_at, lifecycle FROM leads "
            "WHERE lead_id = ? AND link IS NOT NULL AND link <> '' "
            "AND lifecycle != 'promoted' LIMIT 1",
            (lead_id,),
        ).fetchone()
        return [row] if row else []
    days = float(min_interval_hours) / 24.0
    rows = conn.execute(
        "SELECT id, lead_id, title, buyer, link, status_code, status_text, "
        "status_checked_at, lifecycle FROM leads "
        "WHERE link IS NOT NULL AND link <> '' AND lifecycle != 'promoted' "
        "AND (status_code IN ('tender','publicity','unknown') "
        "     OR status_code IS NULL OR status_code = '') "
        "AND COALESCE(fetch_fail_count, 0) < ? "
        "AND (status_checked_at = '' OR status_checked_at IS NULL "
        " OR (julianday(?) - julianday(status_checked_at) >= "
        "   CASE COALESCE(status_code,'') "
        "     WHEN 'publicity' THEN 0.5 "
        "     ELSE 1.0 "
        "   END)) "
        "ORDER BY COALESCE(status_checked_at, '') ASC, id ASC LIMIT ?",
        (FETCH_FAIL_THRESHOLD, _now(), limit),
    ).fetchall()
    return list(rows)


def _record_event(conn, lead_id, old_code, new_code, status_text):
    conn.execute(
        "INSERT INTO events (ts, type, level, module, api, code, msg, payload) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (_now(), "status_transition", "info", "lead_status_check",
         "lead.refresh_status", "STATUS_CHANGED",
         f"{lead_id}: {old_code or '∅'} -> {new_code}",
         json.dumps({"lead_id": lead_id, "old": old_code, "new": new_code,
                     "status_text": status_text[:200]}, ensure_ascii=False)),
    )


def _record_low_confidence(conn, lead_id, new_code, matched):
    """方案2：终态低置信保护——首次判入终态时写独立事件，提示人工看一眼。"""
    conn.execute(
        "INSERT INTO events (ts, type, level, module, api, code, msg, payload) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (_now(), "status_transition", "warn", "lead_status_check",
         "lead.refresh_status", "STATUS_TRANSITION_LOW_CONFIDENCE",
         f"{lead_id} -> {new_code}（低置信）",
         json.dumps({"lead_id": lead_id, "new": new_code, "matched": matched},
                     ensure_ascii=False)),
    )


def _record_unknown(conn, lead_id, status_text):
    """方案3：unknown 反馈环——写事件供 --report-unknown 聚合。"""
    conn.execute(
        "INSERT INTO events (ts, type, level, module, api, code, msg, payload) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (_now(), "status_unknown", "info", "lead_status_check",
         "lead.refresh_status", "STATUS_UNKNOWN",
         f"{lead_id} 状态未知",
         json.dumps({"lead_id": lead_id, "status_text": status_text[:200]},
                     ensure_ascii=False)),
    )


def _update_lead(conn, lead_id, status_text, status_code):
    conn.execute(
        "UPDATE leads SET status_code=?, status_text=?, status_checked_at=?, updated_at=? "
        "WHERE lead_id=?",
        (status_code, status_text[:500], _now(), _now(), lead_id),
    )


def _touch_checked(conn, lead_id):
    conn.execute(
        "UPDATE leads SET status_checked_at=? WHERE lead_id=?",
        (_now(), lead_id),
    )


def _inc_fail_count(conn, lead_id):
    conn.execute(
        "UPDATE leads SET fetch_fail_count=COALESCE(fetch_fail_count,0)+1 WHERE lead_id=?",
        (lead_id,),
    )


def _reset_fail_count(conn, lead_id):
    conn.execute(
        "UPDATE leads SET fetch_fail_count=0 WHERE lead_id=?",
        (lead_id,),
    )


def cmd_check(lead_id, limit, dry_run, min_interval_hours):
    if not DB_PATH.exists():
        raise SystemExit(f"看板库不存在：{DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        rows = _iter_candidates(conn, lead_id, limit, min_interval_hours)
        scanned = len(rows)
        transitioned = unchanged = failed = 0
        details = []
        for r in rows:
            url = r["link"]
            prev_code = r["status_code"] or ""
            try:
                combined, final_url = _fetch_status_text(url)
                new_code, matched = lsn.normalize(combined)
            except Exception as e:
                failed += 1
                _inc_fail_count(conn, r["lead_id"])
                details.append({"lead_id": r["lead_id"], "title": r["title"],
                                "url": url, "err": str(e)[:200]})
                continue
            if new_code == "unknown":
                # 方案3：unknown 反馈环
                if not dry_run:
                    _record_unknown(conn, r["lead_id"], combined)
                    _touch_checked(conn, r["lead_id"])
                    _reset_fail_count(conn, r["lead_id"])
                details.append({
                    "lead_id": r["lead_id"], "title": r["title"][:50],
                    "url": final_url, "prev": prev_code, "new": new_code,
                    "matched": matched, "changed": False, "unknown": True,
                })
                unchanged += 1
                continue
            changed = (new_code != prev_code)
            if changed:
                transitioned += 1
                if not dry_run:
                    _update_lead(conn, r["lead_id"], combined, new_code)
                    _record_event(conn, r["lead_id"], prev_code, new_code, combined)
                    # 方案2：终态低置信保护
                    if new_code in ("awarded", "delivered", "closed"):
                        _record_low_confidence(conn, r["lead_id"], new_code, matched)
                    _reset_fail_count(conn, r["lead_id"])
            else:
                unchanged += 1
                if not dry_run:
                    _touch_checked(conn, r["lead_id"])
                    _reset_fail_count(conn, r["lead_id"])
            details.append({
                "lead_id": r["lead_id"], "title": r["title"][:50],
                "url": final_url, "prev": prev_code, "new": new_code,
                "matched": matched, "changed": changed,
            })
        if not dry_run:
            conn.commit()
        return {"scanned": scanned, "transitioned": transitioned,
                "unchanged": unchanged, "failed": failed,
                "details": details[:20]}
    finally:
        conn.close()


def cmd_report_unknown(days=7, limit=10):
    """方案3：unknown 反馈环聚合——输出 Top-N 未覆盖短语。"""
    if not DB_PATH.exists():
        raise SystemExit(f"看板库不存在：{DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT ts, payload FROM events "
            "WHERE code='STATUS_UNKNOWN' AND julianday(?) - julianday(ts) < ? "
            "ORDER BY ts DESC LIMIT 200",
            (_now(), float(days)),
        ).fetchall()
        clusters: dict[str, list[str]] = {}
        for r in rows:
            try:
                p = json.loads(r["payload"])
                txt = p.get("status_text", "")[:60]
            except Exception:
                continue
            # 按前 8 字粗聚类
            key = txt[:8] if txt else "(空)"
            clusters.setdefault(key, []).append(txt)
        ranked = sorted(clusters.items(), key=lambda kv: -len(kv[1]))[:limit]
        print(f"近 {days} 天 STATUS_UNKNOWN 共 {sum(len(v) for v in clusters.values())} 条，聚类 {len(clusters)} 组：")
        for i, (key, samples) in enumerate(ranked, 1):
            print(f"  {i}. 【{len(samples)} 条】{key!r} → 样例：{samples[0]!r}")
        return {"clusters": len(clusters), "top": ranked}
    finally:
        conn.close()


# ---------- 自测 ----------

class _MockResp:
    def __init__(self, body: bytes, url: str):
        self._body = body
        self._url = url
    def read(self, n=None):
        return self._body[:n] if n else self._body
    def close(self):
        pass
    def getcode(self):
        return 200
    def geturl(self):
        return self._url


def _selftest() -> int:
    """构造假 lead + mock safe_fetch.fetch，验证状态转移 + 分频 + 低置信 + unknown 反馈。"""
    import tempfile
    fails = 0

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        tmp_db = Path(tf.name)

    conn = sqlite3.connect(str(tmp_db), timeout=15)
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "ts TEXT, type TEXT, level TEXT, module TEXT, api TEXT, "
                 "code TEXT, msg TEXT, payload TEXT)")
    conn.execute("CREATE TABLE leads (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "lead_id TEXT, title TEXT, buyer TEXT, link TEXT, "
                 "status_code TEXT DEFAULT '', status_text TEXT DEFAULT '', "
                 "status_checked_at TEXT DEFAULT '', lifecycle TEXT DEFAULT 'new', "
                 "updated_at TEXT DEFAULT '', fetch_fail_count INTEGER DEFAULT 0)")
    # L1: tender -> awarded（终态，应写 STATUS_CHANGED + STATUS_TRANSITION_LOW_CONFIDENCE）
    conn.execute("INSERT INTO leads (lead_id, title, link, status_code, status_text) "
                 "VALUES (?, ?, ?, ?, ?)", ("L1", "测试A", "https://example.com/a", "tender", "招标中"))
    # L2: tender 不变（应刷新时间 + 清零 fail_count）
    conn.execute("INSERT INTO leads (lead_id, title, link, status_code, status_text) "
                 "VALUES (?, ?, ?, ?, ?)", ("L2", "测试B", "https://example.com/b", "tender", "招标中"))
    # L3: tender -> unknown（应写 STATUS_UNKNOWN 事件）
    conn.execute("INSERT INTO leads (lead_id, title, link, status_code, status_text) "
                 "VALUES (?, ?, ?, ?, ?)", ("L3", "测试C", "https://example.com/c", "tender", "招标公告"))
    # L4: 无 link（应被过滤）
    conn.execute("INSERT INTO leads (lead_id, title, link, status_code) "
                 "VALUES (?, ?, ?, ?)", ("L4", "测试D", "", "tender"))
    # L5: promoted（应被过滤）
    conn.execute("INSERT INTO leads (lead_id, title, link, status_code, lifecycle) "
                 "VALUES (?, ?, ?, ?, ?)", ("L5", "测试E", "https://example.com/e", "tender", "promoted"))
    # L6: awarded（终态，不应进入候选）
    conn.execute("INSERT INTO leads (lead_id, title, link, status_code, status_text) "
                 "VALUES (?, ?, ?, ?, ?)", ("L6", "测试F", "https://example.com/f", "awarded", "已中标"))
    # L7: fetch_fail_count=5（应出队）
    conn.execute("INSERT INTO leads (lead_id, title, link, status_code, status_text, fetch_fail_count) "
                 "VALUES (?, ?, ?, ?, ?, ?)", ("L7", "测试G", "https://example.com/g", "tender", "招标中", 5))
    conn.commit()
    conn.close()

    mock_pages = {
        "https://example.com/a": "<html><head><title>XX中标公告</title></head><body>已中标</body></html>",
        "https://example.com/b": "<html><head><title>XX招标公告</title></head><body>招标中</body></html>",
        "https://example.com/c": "<html><head><title>XX未知页</title></head><body>评审中</body></html>",
    }
    original_fetch = safe_fetch.fetch
    safe_fetch.fetch = lambda url, **kw: (mock_pages[url].encode("utf-8"), url)

    original_db = DB_PATH
    globals()["DB_PATH"] = tmp_db
    try:
        result = cmd_check(lead_id=None, limit=50, dry_run=False, min_interval_hours=0)
    finally:
        safe_fetch.fetch = original_fetch
        globals()["DB_PATH"] = original_db

    print(f"扫描 {result['scanned']} · 转移 {result['transitioned']} · 不变 {result['unchanged']} · 失败 {result['failed']}")

    conn2 = sqlite3.connect(str(tmp_db))
    # L1: tender -> awarded + 低置信
    row = conn2.execute("SELECT status_code FROM leads WHERE lead_id='L1'").fetchone()
    if row[0] != "awarded":
        fails += 1
        print(f"   X L1 应 awarded，实际 {row[0]}")
    else:
        print("OK L1: tender -> awarded")
    low = conn2.execute("SELECT COUNT(*) FROM events WHERE code='STATUS_TRANSITION_LOW_CONFIDENCE' AND payload LIKE '%L1%'").fetchone()[0]
    if low != 1:
        fails += 1
        print(f"   X L1 低置信事件应 1，实际 {low}")
    else:
        print("OK L1 低置信事件 1")

    # L2: tender 保持 + 时间刷 + fail_count 清零
    row = conn2.execute("SELECT status_code, status_checked_at, fetch_fail_count FROM leads WHERE lead_id='L2'").fetchone()
    if row[0] != "tender" or not row[1] or row[2] != 0:
        fails += 1
        print(f"   X L2 应保持 tender 且时间已刷 fail=0：{row[0]} / {row[1]} / {row[2]}")
    else:
        print("OK L2: tender 保持 + 时间刷新 + fail_count 清零")

    # L3: unknown 反馈
    row = conn2.execute("SELECT status_code FROM leads WHERE lead_id='L3'").fetchone()
    if row[0] != "tender":
        fails += 1
        print(f"   X L3 应保持 tender（unknown 不回写），实际 {row[0]}")
    else:
        print("OK L3: tender 保持（unknown 不回写）")
    unk = conn2.execute("SELECT COUNT(*) FROM events WHERE code='STATUS_UNKNOWN' AND payload LIKE '%L3%'").fetchone()[0]
    if unk != 1:
        fails += 1
        print(f"   X L3 STATUS_UNKNOWN 应 1，实际 {unk}")
    else:
        print("OK L3 STATUS_UNKNOWN 1")

    # L4/L5 过滤
    if any(d["lead_id"] == "L4" for d in result["details"]):
        fails += 1
        print("   X L4 无 link 应过滤")
    else:
        print("OK L4 无 link 过滤")
    if any(d["lead_id"] == "L5" for d in result["details"]):
        fails += 1
        print("   X L5 promoted 应过滤")
    else:
        print("OK L5 promoted 过滤")

    # L6 终态不出候选
    if any(d["lead_id"] == "L6" for d in result["details"]):
        fails += 1
        print("   X L6 awarded 终态应排除")
    else:
        print("OK L6 awarded 终态排除")

    # L7 fail_count 出队
    if any(d["lead_id"] == "L7" for d in result["details"]):
        fails += 1
        print("   X L7 fail_count=5 应出队")
    else:
        print("OK L7 fail_count=5 出队")

    conn2.close()
    tmp_db.unlink(missing_ok=True)

    if fails:
        print(f"\nFAIL selftest 失败 {fails}")
        return 1
    print(f"\nPASS selftest 通过")
    return 0


def cmd_report_unknown_cli(days=7, limit=10):
    """CLI 入口：--report-unknown [days] [limit]"""
    out = cmd_report_unknown(days=days, limit=limit)
    return out


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test":
        sys.exit(_selftest())
    if len(sys.argv) >= 2 and sys.argv[1] == "--report-unknown":
        days = int(sys.argv[2]) if len(sys.argv) >= 3 else 7
        limit = int(sys.argv[3]) if len(sys.argv) >= 4 else 10
        cmd_report_unknown_cli(days=days, limit=limit)
        return

    ap = argparse.ArgumentParser(description="标讯历史状态复核（5态机拉原文侦测转移）")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"每批最多复核条数（默认 {DEFAULT_LIMIT}）")
    ap.add_argument("--lead", default=None, help="单条复核（lead_id 字符串）")
    ap.add_argument("--dry-run", action="store_true", help="只打印不写库")
    ap.add_argument("--min-interval-hours", type=int, default=MIN_INTERVAL_HOURS, help=f"复核频率下限（默认 {MIN_INTERVAL_HOURS}h；0=不限）")
    args = ap.parse_args()

    t0 = time.time()
    out = cmd_check(args.lead, args.limit, args.dry_run, args.min_interval_hours)
    elapsed = round(time.time() - t0, 1)
    print(f"扫描 {out['scanned']} · 转移 {out['transitioned']} · 不变 {out['unchanged']} · "
          f"失败 {out['failed']} · {elapsed}s")
    for d in out["details"]:
        if d.get("changed"):
            print(f"  >> {d['lead_id']} {d['prev']}->{d['new']} (matched={d['matched']!r})")
        elif d.get("unknown"):
            print(f"  ?? {d['lead_id']} unknown (matched={d['matched']!r})")
        elif "err" in d:
            print(f"  XX {d['lead_id']} err={d['err']}")


if __name__ == "__main__":
    sys.exit(main() or 0)
