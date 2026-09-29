#!/usr/bin/env python3
"""digest_stats.py · M6 Step 1 · 生成今日纯数据统计
- 输入: truth.db(bid_profile) + app.db(leads/events)——DEV-0042 单系统整合
- 输出: ~/.bidmaster/digests/.tmp/YYYY-MM-DD.stats.json
- 零依赖(stdlib + sqlite3)
- 不调 LLM、不调外部 API、纯聚合
"""
import json
import os
import sys
import sqlite3
from datetime import datetime, date
from pathlib import Path

_DATA_ROOT = Path(os.environ.get("BIDMASTER_HOME") or (Path.home() / ".bidmaster"))
TRUTH_DB = _DATA_ROOT / "truth.db"      # bids 权威 + bid_profile（看板字段）
APP_DB = _DATA_ROOT / "app.db"          # leads / events（服务自有库）
OUT_DIR = _DATA_ROOT / "digests" / ".tmp"
TODAY = date.today().strftime("%Y-%m-%d")
OUT_FILE = OUT_DIR / f"{TODAY}.stats.json"


def _ensure_inside(base_dir, target):
    """路径穿越防护:目标文件解析后的真实路径必须位于 base_dir 之下,否则拒绝写入。"""
    base = Path(base_dir).resolve()
    t = Path(target).resolve()
    if t.parent != base and base not in t.parents:
        raise SystemExit(f"输出路径越界,拒绝写入: {target}")
    return t


def safe_query(conn, sql, params=(), default=None):
    """安全查询:出错不崩,返回 default(list)"""
    try:
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        return default if default is not None else []


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not TRUTH_DB.exists() and not APP_DB.exists():
        print(json.dumps(
            {"ok": False, "err": f"数据面不存在: {_DATA_ROOT}"},
            ensure_ascii=False
        ))
        sys.exit(1)

    # bids 维度：truth.db bid_profile（字段在 data JSON 里）
    bids_all = []
    if TRUTH_DB.exists():
        tconn = sqlite3.connect(str(TRUTH_DB), timeout=10)
        tconn.row_factory = sqlite3.Row
        bids_all = safe_query(tconn,
            "SELECT bid_id, data, stage, priority, industry, region, est_amount, "
            "lifecycle, updated_at FROM bid_profile")
        tconn.close()
    for b in bids_all:
        b.setdefault("code", b.get("bid_id"))
        b.setdefault("created_at", "")

    # leads / events 维度：app.db
    leads_all, events_today = [], []
    if APP_DB.exists():
        conn = sqlite3.connect(str(APP_DB), timeout=10)
        conn.row_factory = sqlite3.Row
        leads_all = safe_query(conn,
            "SELECT lead_id, title, buyer, industry, region, amount, score, "
            "recommend, lifecycle, created_at FROM leads")
        events_today = safe_query(conn,
            "SELECT type, level, module, api, code, msg, ts FROM events WHERE ts LIKE ?",
            (f"{TODAY}%",))
        conn.close()

    # bids.data 是 JSON 字符串,展开 client / due_at / human_todo / ai_ready
    for b in bids_all:
        try:
            data = json.loads(b.get("data") or "{}")
        except Exception:
            data = {}
        b["client"] = data.get("client", "")
        b["due_at"] = data.get("due_at", "")
        b.setdefault("created_at", data.get("created_at", ""))

    stats = {
        "date": TODAY,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        # bids 维度
        "bids_total": len(bids_all),
        "bids_by_stage": {},
        "bids_by_priority": {"P0": 0, "P1": 0, "P2": 0},
        "bids_by_industry": {},
        "bids_by_region": {},
        "bids_amount_sum": 0.0,
        "bids_recent": [],
        # leads 维度
        "leads_total": len(leads_all),
        "leads_by_recommend": {"P0": 0, "P1": 0, "P2": 0, "跳过": 0},
        "leads_p0_pending": [],
        # events
        "events_today_count": len(events_today),
        "events_today_modules": {},
    }

    now = datetime.now()
    for b in bids_all:
        stage = b.get("stage") or "未知"
        stats["bids_by_stage"][stage] = stats["bids_by_stage"].get(stage, 0) + 1

        pri = b.get("priority") or ""
        if pri in ("P0", "P1", "P2"):
            stats["bids_by_priority"][pri] += 1

        ind = b.get("industry") or "通用"
        stats["bids_by_industry"][ind] = stats["bids_by_industry"].get(ind, 0) + 1

        reg = b.get("region") or "全国"
        stats["bids_by_region"][reg] = stats["bids_by_region"].get(reg, 0) + 1

        try:
            stats["bids_amount_sum"] += float(b.get("est_amount") or 0)
        except Exception:
            pass

        # 最近 7 天创建的 bid
        try:
            created_str = (b.get("created_at") or "")[:10]
            if created_str:
                created = datetime.strptime(created_str, "%Y-%m-%d")
                if (now - created).days <= 7:
                    stats["bids_recent"].append({
                        "code": b.get("code"),
                        "client": b.get("client"),
                        "stage": b.get("stage"),
                        "priority": b.get("priority"),
                        "created": created_str,
                    })
        except Exception:
            pass

    for l in leads_all:
        rec = l.get("recommend") or "跳过"
        if rec in stats["leads_by_recommend"]:
            stats["leads_by_recommend"][rec] += 1

        # P0 待升级:lifecycle=new 且还没转 bid
        if rec == "P0" and (l.get("lifecycle") or "new") == "new":
            stats["leads_p0_pending"].append({
                "lead_id": l.get("lead_id"),
                "title": (l.get("title") or "")[:50],
                "buyer": l.get("buyer") or "",
                "score": l.get("score", 0),
                "amount": l.get("amount"),
            })

    for e in events_today:
        mod = e.get("module") or "?"
        stats["events_today_modules"][mod] = stats["events_today_modules"].get(mod, 0) + 1

    # 写文件(路径穿越防护:规范化后必须位于 OUT_DIR 之下,且不含 ..)
    base_real = os.path.realpath(str(OUT_DIR))
    out_real = os.path.realpath(os.path.normpath(str(_ensure_inside(OUT_DIR, OUT_FILE))))
    if ".." in str(OUT_FILE) or not out_real.startswith(base_real + os.sep):
        raise SystemExit(f"输出路径越界,拒绝写入: {OUT_FILE}")
    Path(out_real).write_text(
        json.dumps(stats, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    conn.close()

    print(json.dumps({
        "ok": True,
        "module": "digest_stats",
        "out": str(OUT_FILE),
        "bids": stats["bids_total"],
        "leads": stats["leads_total"],
        "events_today": stats["events_today_count"],
        "p0_pending": len(stats["leads_p0_pending"]),
        "bids_recent_7d": len(stats["bids_recent"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
