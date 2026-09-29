#!/usr/bin/env python3
"""app/services/lead_store.py · lead 观察层数据服务（自 server.py 1058-1157/877-986 迁移）

lead_id 统一派生（DEV-0042 收敛）：缺省时 sha256(title|buyer)[:16]——
与 rules/import_xlsx_leads.py 同一规则；已带 lead_id 的行原样保留。
"""
import hashlib
import json
import sqlite3
from datetime import datetime, date

from .. import config
from ..store import app_db
from . import lead_gate, notify


def derive_lead_id(title: str, buyer: str) -> str:
    """lead_id 单一派生规则（收敛 lead_capture 的 sha1(url)[:12] 与 xlsx 的 sha256(title|buyer) 双轨）。"""
    raw = f"{(title or '').strip()}|{(buyer or '').strip()}"
    return "lead-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def save_lead(lead) -> bool:
    """写一条 lead（watcher 或命令调用）。幂等:同 (title+buyer+source) 唯一。
    入库前走质量门禁,不合格拒入 + warn 日志。"""
    ok, reason = lead_gate.validate_lead_quality(lead)
    if not ok:
        notify.log_module("gate", f"🚫 lead 拒入: {reason} · {lead.get('title', '')[:40]}", "warn")
        return False
    try:
        conn = sqlite3.connect(str(config.APP_DB_PATH))
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT id FROM leads WHERE title=? AND buyer=? AND source=?",
            (lead.get("title", ""), lead.get("buyer", ""), lead.get("source", ""))
        ).fetchone()
        if existing:
            # DEV-0042：qualify.jsonl 回写通道——同 lead 再入且带评分时更新评分字段
            # （原由 qualify_score.py 跨进程直写 DB，现收敛到本 watcher 统一入口）
            if lead.get("score") or lead.get("recommend"):
                conn.execute(
                    "UPDATE leads SET score=COALESCE(NULLIF(?,0), score), recommend=CASE WHEN ?<>'' THEN ? ELSE recommend END, reason=CASE WHEN ?<>'' THEN ? ELSE reason END, updated_at=? WHERE id=?",
                    (int(lead.get("score", 0) or 0), lead.get("recommend", ""), lead.get("recommend", ""),
                     lead.get("reason", ""), lead.get("reason", ""),
                     datetime.now().strftime("%Y-%m-%d %H:%M:%S"), existing["id"]))
                conn.commit()
            conn.close()
            return False
        now = datetime.now()
        lead_id = lead.get("lead_id", "") or derive_lead_id(lead.get("title", ""), lead.get("buyer", ""))
        conn.execute(
            "INSERT INTO leads (lead_id, ts, title, buyer, industry, region, amount, deadline, published_at, source, link, raw_keywords, score, recommend, reason, lifecycle, freshness, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (lead_id,
             lead.get("ts", ""),
             lead.get("title", ""),
             lead.get("buyer", ""),
             lead.get("industry", ""),
             lead.get("region", ""),
             lead.get("amount", 0),
             lead.get("deadline", ""),
             lead.get("published_at", ""),  # 时效门禁必需
             lead.get("source", ""),
             lead.get("link", ""),
             lead.get("raw_keywords", ""),
             lead.get("score", 0),
             lead.get("recommend", ""),
             lead.get("reason", ""),
             "new",          # lifecycle 业务流转态
             "fresh",        # freshness 时效态（关闭区用）
             now.strftime("%Y-%m-%d %H:%M:%S"),
             now.strftime("%Y-%m-%d %H:%M:%S"),
             ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[db] save_lead failed: {e}", file=__import__("sys").stderr)
        return False


def scan_lead_freshness(force_rescan=False):
    """关闭区:扫描 lead 时效状态,自动归档过期 lead。

    时效状态机（独立于业务 lifecycle）:
      fresh: < aging_threshold / aging: ~ FRESH_DAYS / expired: > FRESH_DAYS（关闭区）
      跳过已 promoted 的 lead（已升级到 bid 的不过期）。
    """
    today = date.today()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    aging_threshold = int(config.LEAD_FRESH_DAYS * 0.66)

    conn = sqlite3.connect(str(config.APP_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, lead_id, published_at, lifecycle, freshness, archived_at FROM leads"
        ).fetchall()
    except Exception as e:
        conn.close()
        print(f"[scan] lead freshness 扫描失败: {e}", file=__import__("sys").stderr)
        return {"scanned": 0, "expired": [], "aging": [], "freshened": [], "err": str(e)}

    expired_ids, aging_ids, freshened_ids = [], [], []
    skip_count = 0
    update_pairs = []

    for r in rows:
        rid = r["id"]
        lead_id = r["lead_id"]
        pub = (r["published_at"] or "").strip()
        biz_lc = (r["lifecycle"] or "new").strip()
        old_freshness = (r["freshness"] or "fresh").strip()
        old_archived_at = (r["archived_at"] or "").strip()

        if biz_lc == "promoted":
            skip_count += 1
            continue
        if not pub:
            continue
        try:
            pub_date = datetime.strptime(pub[:10], "%Y-%m-%d").date()
        except Exception:
            continue
        days_old = (today - pub_date).days

        if days_old > config.LEAD_FRESH_DAYS:
            new_freshness = "expired"
            new_archived_at = now_str if not old_archived_at else old_archived_at
        elif days_old >= aging_threshold:
            new_freshness = "aging"
            new_archived_at = ""
        else:
            new_freshness = "fresh"
            new_archived_at = ""

        if new_freshness != old_freshness or (new_freshness == "expired" and not old_archived_at):
            update_pairs.append((new_freshness, new_archived_at, rid))
            if new_freshness == "expired" and old_freshness != "expired":
                expired_ids.append(lead_id)
            elif new_freshness == "aging" and old_freshness != "aging":
                aging_ids.append(lead_id)
            elif new_freshness == "fresh" and old_freshness in ("aging", "expired") and force_rescan:
                freshened_ids.append(lead_id)

    if update_pairs:
        try:
            conn.executemany(
                "UPDATE leads SET freshness=?, archived_at=? WHERE id=?",
                update_pairs
            )
            conn.commit()
        except Exception as e:
            conn.close()
            print(f"[scan] batch update failed: {e}", file=__import__("sys").stderr)
            return {"scanned": len(rows), "expired": expired_ids, "aging": aging_ids,
                    "freshened": freshened_ids, "skip": skip_count, "err": str(e)}
    conn.close()
    return {
        "scanned": len(rows),
        "skip": skip_count,
        "expired": expired_ids,
        "aging": aging_ids,
        "freshened": freshened_ids,
    }


def purge_stale_leads() -> int:
    """boot 自愈：物理删除距今 > 2 * FRESH_DAYS 的软过期 lead（定向删除，幂等）。"""
    today = date.today()
    threshold_days = config.LEAD_FRESH_DAYS * 2
    conn = sqlite3.connect(str(config.APP_DB_PATH))
    conn.row_factory = sqlite3.Row
    stale_ids = []
    try:
        for r in conn.execute("SELECT lead_id, published_at FROM leads").fetchall():
            pub = (r["published_at"] or "").strip()
            if not pub:
                continue
            try:
                pub_date = datetime.strptime(pub[:10], "%Y-%m-%d").date()
                if (today - pub_date).days > threshold_days:
                    stale_ids.append(r["lead_id"] or "")
            except Exception:
                continue
        if stale_ids:
            conn.executemany("DELETE FROM leads WHERE lead_id=?", [(x,) for x in stale_ids if x])
            conn.commit()
            print(f"[init] 🧹 自愈清理:定向删除 {len(stale_ids)} 条过期 lead(>{threshold_days} 天)", file=__import__("sys").stderr)
    except Exception as e:
        print(f"[init] 自愈清理失败: {e}", file=__import__("sys").stderr)
    finally:
        conn.close()
    return len(stale_ids)


def closed_leads(limit=500) -> list:
    """关闭区：freshness=expired 的 lead，附 days_old。"""
    leads = app_db.load_leads(limit=limit, freshness="expired")
    today = date.today()
    for lead in leads:
        pub = (lead.get("published_at") or "").strip()
        if pub:
            try:
                pub_date = datetime.strptime(pub[:10], "%Y-%m-%d").date()
                lead["days_old"] = (today - pub_date).days
            except Exception:
                lead["days_old"] = None
    return leads
