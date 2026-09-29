#!/usr/bin/env python3
"""app/store/app_db.py · 服务自有库（观察层，DEV-0042）

职责：leads（观察层）/ events / command_execution（命令审计）/ activity_log / collection_run。
标域权威在 truth.db（rules/store.py），本库不存 bid——bid_profile 已入真实层。
schema 自原 server.py _db_init 收敛：bids 表移除（入 truth.bid_profile）、archive 死表移除、
ALTER 迁移收敛为初始 DDL（数据面 2026-09-12 清空，无存量迁移负担）。
"""
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .. import config

DB_LOCK = threading.RLock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.APP_DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init() -> None:
    """建表（幂等，CREATE IF NOT EXISTS，绝不 DROP——数据不能丢）。"""
    config.ensure_dirs()
    conn = _connect()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            type TEXT,
            level TEXT,
            module TEXT,
            api TEXT,
            code TEXT,
            msg TEXT,
            payload TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_events_code ON events(code);
        CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);

        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT,
            ts TEXT,
            title TEXT,
            buyer TEXT,
            industry TEXT,
            region TEXT,
            amount REAL,
            deadline TEXT,
            published_at TEXT,
            source TEXT,
            link TEXT,
            raw_keywords TEXT,
            score INTEGER,
            recommend TEXT,
            reason TEXT,
            lifecycle TEXT DEFAULT 'new',
            promoted_to_bid TEXT,
            created_at TEXT,
            updated_at TEXT,
            freshness TEXT DEFAULT 'fresh',
            archived_at TEXT,
            phase TEXT DEFAULT '',
            buyer_level TEXT DEFAULT '',
            sub_industry TEXT DEFAULT '',
            sales_owner TEXT DEFAULT '',
            status_code TEXT DEFAULT '',
            status_text TEXT DEFAULT '',
            status_checked_at TEXT DEFAULT '',
            agency TEXT DEFAULT '',
            fetch_fail_count INTEGER DEFAULT 0,
            provenance TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_leads_recommend ON leads(recommend);
        CREATE INDEX IF NOT EXISTS idx_leads_lifecycle ON leads(lifecycle);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_unique ON leads(title, buyer, source);
        CREATE INDEX IF NOT EXISTS idx_leads_freshness ON leads(freshness, archived_at);

        CREATE TABLE IF NOT EXISTS command_execution (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id TEXT UNIQUE NOT NULL,
            commandId TEXT NOT NULL,
            idempotency_key TEXT,
            payload_hash TEXT,
            agent_id TEXT,
            params TEXT,
            result TEXT,
            status TEXT NOT NULL,
            error TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_cmd_idem ON command_execution(idempotency_key);
        CREATE INDEX IF NOT EXISTS idx_cmd_code ON command_execution(commandId);
        CREATE INDEX IF NOT EXISTS idx_cmd_created ON command_execution(created_at DESC);

        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            actor TEXT,
            action TEXT,
            target_type TEXT,
            target_id TEXT,
            payload TEXT,
            execution_id TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_act_target ON activity_log(target_type, target_id);
        CREATE INDEX IF NOT EXISTS idx_act_ts ON activity_log(ts DESC);

        CREATE TABLE IF NOT EXISTS collection_run (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT UNIQUE NOT NULL,
            source TEXT,
            channel_name TEXT,
            status TEXT,
            items_count INTEGER DEFAULT 0,
            applied_count INTEGER DEFAULT 0,
            rejected_count INTEGER DEFAULT 0,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            payload_hash TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_col_run_started ON collection_run(started_at DESC);

        CREATE TABLE IF NOT EXISTS skill_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT UNIQUE NOT NULL,
            skill_id TEXT NOT NULL,
            bid_id TEXT,
            agent_id TEXT DEFAULT 'kanban',
            status TEXT NOT NULL,
            params TEXT,
            result TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_sk_bid ON skill_runs(bid_id);
        CREATE INDEX IF NOT EXISTS idx_sk_started ON skill_runs(started_at DESC);

        CREATE TABLE IF NOT EXISTS next_actions (
            bid_id TEXT PRIMARY KEY,
            skill TEXT,
            playbook TEXT,
            label TEXT NOT NULL,
            icon TEXT DEFAULT '',
            reason TEXT DEFAULT '',
            source TEXT DEFAULT 'zcode',
            updated_at TEXT NOT NULL
        );
        """)
        existing = {r[1] for r in conn.execute("PRAGMA table_info(leads)").fetchall()}
        if "status_code" not in existing:
            conn.execute("ALTER TABLE leads ADD COLUMN status_code TEXT DEFAULT ''")
        if "status_text" not in existing:
            conn.execute("ALTER TABLE leads ADD COLUMN status_text TEXT DEFAULT ''")
        if "status_checked_at" not in existing:
            conn.execute("ALTER TABLE leads ADD COLUMN status_checked_at TEXT DEFAULT ''")
        if "agency" not in existing:
            conn.execute("ALTER TABLE leads ADD COLUMN agency TEXT DEFAULT ''")
        if "fetch_fail_count" not in existing:
            conn.execute("ALTER TABLE leads ADD COLUMN fetch_fail_count INTEGER DEFAULT 0")
        # R4（工程审查 2026-09-19）：线索来历——"这条线索实际是怎么来的"（抓取失败后的真实补录路径）
        if "provenance" not in existing:
            conn.execute("ALTER TABLE leads ADD COLUMN provenance TEXT DEFAULT ''")
        # 索引在 ALTER 迁移完成后创建，确保列已存在
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status_code, status_checked_at)")
        conn.commit()
    finally:
        conn.close()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ────────────────────────── events ──────────────────────────
def save_event(ev: dict) -> None:
    try:
        with DB_LOCK:
            conn = _connect()
            conn.execute(
                "INSERT INTO events (ts, type, level, module, api, code, msg, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ev.get("ts", now_str()), ev.get("type", "api"), ev.get("level", "info"),
                 ev.get("module", "api"), ev.get("api", ""), ev.get("code", ""),
                 ev.get("msg", ""),
                 json.dumps(ev.get("payload", {}), ensure_ascii=False, default=str)))
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"[db] save_event failed: {e}", file=__import__("sys").stderr)


def save_event_in_conn(conn, ev: dict) -> None:
    conn.execute(
        "INSERT INTO events (ts, type, level, module, api, code, msg, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ev.get("ts", now_str()), ev.get("type", "api"), ev.get("level", "info"),
         ev.get("module", "api"), ev.get("api", ""), ev.get("code", ""),
         ev.get("msg", ""),
         json.dumps(ev.get("payload", {}), ensure_ascii=False, default=str)))


def load_events(limit=200) -> list:
    if not config.APP_DB_PATH.exists():
        return []
    try:
        conn = _connect()
        rows = conn.execute(
            "SELECT ts, type, level, module, api, code, msg, payload FROM events ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
        conn.close()
        events = []
        for r in rows:
            ev = {"ts": r["ts"], "type": r["type"], "level": r["level"] or "info",
                  "module": r["module"] or "", "api": r["api"] or "", "code": r["code"] or "",
                  "msg": r["msg"] or ""}
            try:
                ev["payload"] = json.loads(r["payload"]) if r["payload"] else {}
            except Exception:
                ev["payload"] = {}
            events.append(ev)
        return events
    except Exception as e:
        print(f"[db] load_events failed: {e}", file=__import__("sys").stderr)
        return []


# ────────────────────────── leads ──────────────────────────
_LEAD_COLS = ("id, lead_id, ts, title, buyer, industry, region, amount, deadline, published_at, "
              "source, link, raw_keywords, score, recommend, reason, lifecycle, freshness, "
              "archived_at, promoted_to_bid, phase, buyer_level, sub_industry, sales_owner, "
              "agency")

_LEAD_SORTS = {
    # 排序白名单（键 → SQL ORDER BY 片段，全部字面量；priority/phase 按业务序）
    "time": "published_at",
    "amount": "amount",
    "priority": "CASE COALESCE(recommend,'') WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END",
    "phase": "CASE COALESCE(phase,'') WHEN '线索期' THEN 0 WHEN '发标' THEN 1 WHEN '投标' THEN 2 WHEN '述标' THEN 3 WHEN '公示' THEN 4 WHEN '交付' THEN 5 WHEN '回款' THEN 6 ELSE 7 END",
    "buyer_level": "buyer_level",
    "sub_industry": "sub_industry",
}


def load_leads(limit=200, recommend=None, freshness=None, sort=None, order=None, phase=None) -> list:
    try:
        conn = _connect()
        where, params = [], []
        # DEV-0064：丢弃（lifecycle='discarded'）不在默认列表出现——确认丢弃即从视图删除，
        # 行保留供审计（关闭区/DB 直查可见）
        where.append("lifecycle != 'discarded'")
        if recommend:
            where.append("recommend=?")
            params.append(recommend)
        if freshness:
            where.append("freshness=?")
            params.append(freshness)
        if phase:
            where.append("phase=?")
            params.append(phase)
        sql_where = ("WHERE " + " AND ".join(where)) if where else ""
        sort_sql = _LEAD_SORTS.get(sort) if sort else None
        direction = "ASC" if (order or "").lower() == "asc" else "DESC"
        if sort_sql:
            sql = f"SELECT {_LEAD_COLS} FROM leads {sql_where} ORDER BY {sort_sql} {direction}, id DESC LIMIT ?"
        else:
            sql = f"SELECT {_LEAD_COLS} FROM leads {sql_where} ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] load_leads failed: {e}", file=__import__("sys").stderr)
        return []


def get_lead(lead_id: str):
    """按 lead_id（或数字主键）取 lead 行（sqlite3.Row 或 None）。"""
    conn = _connect()
    try:
        try:
            pk = int(lead_id)
            row = conn.execute("SELECT * FROM leads WHERE id=?", (pk,)).fetchone()
            if row:
                return row
        except (ValueError, TypeError):
            pass
        return conn.execute("SELECT * FROM leads WHERE lead_id=?", (lead_id,)).fetchone()
    finally:
        conn.close()


# ────────────────────────── 命令审计 ──────────────────────────
def log_activity_in_conn(conn, actor, action, target_type, target_id, payload, execution_id=""):
    conn.execute(
        "INSERT INTO activity_log (ts, actor, action, target_type, target_id, payload, execution_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now_str(), actor, action, target_type, target_id,
         json.dumps(payload, ensure_ascii=False, default=str), execution_id))


def get_execution(execution_id: str):
    with DB_LOCK:
        conn = _connect()
        row = conn.execute(
            "SELECT execution_id, commandId, status, params, result, error, agent_id, idempotency_key, created_at, completed_at FROM command_execution WHERE execution_id=?",
            (execution_id,)).fetchone()
        conn.close()
    return dict(row) if row else None


# ────────────────────────── skill_runs ──────────────────────────
def create_skill_run(skill_id, bid_id, agent_id="kanban", params=None) -> str:
    """创建 skill_runs 行（status=running），返回 run_id。"""
    import secrets
    run_id = f"sk_{int(datetime.now().timestamp())}_{secrets.token_hex(3)}"
    with DB_LOCK:
        conn = _connect()
        conn.execute(
            "INSERT INTO skill_runs (run_id, skill_id, bid_id, agent_id, status, params, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, skill_id, bid_id or "", agent_id, "running",
             json.dumps(params or {}, ensure_ascii=False), now_str()))
        conn.commit()
        conn.close()
    return run_id


def complete_skill_run(run_id, status, result=None) -> None:
    """更新 skill_runs 行为 completed/failed。"""
    with DB_LOCK:
        conn = _connect()
        conn.execute(
            "UPDATE skill_runs SET status=?, result=?, completed_at=? WHERE run_id=?",
            (status, json.dumps(result or {}, ensure_ascii=False), now_str(), run_id))
        conn.commit()
        conn.close()


def list_skill_runs(bid_id=None, limit=20) -> list:
    """列出 skill 执行记录（可选按 bid_id 过滤）。"""
    conn = _connect()
    try:
        if bid_id:
            rows = conn.execute(
                "SELECT run_id, skill_id, bid_id, agent_id, status, params, result, started_at, completed_at FROM skill_runs WHERE bid_id=? ORDER BY started_at DESC LIMIT ?",
                (bid_id, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT run_id, skill_id, bid_id, agent_id, status, params, result, started_at, completed_at FROM skill_runs ORDER BY started_at DESC LIMIT ?",
                (limit,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["params"] = json.loads(d["params"]) if d["params"] else {}
            except Exception:
                pass
            try:
                d["result"] = json.loads(d["result"]) if d["result"] else {}
            except Exception:
                pass
            result.append(d)
        return result
    finally:
        conn.close()


def get_skill_run(run_id: str):
    """单条 skill 执行详情。"""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT run_id, skill_id, bid_id, agent_id, status, params, result, started_at, completed_at FROM skill_runs WHERE run_id=?",
            (run_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["params"] = json.loads(d["params"]) if d["params"] else {}
        except Exception:
            pass
        try:
            d["result"] = json.loads(d["result"]) if d["result"] else {}
        except Exception:
            pass
        return d
    finally:
        conn.close()


# ────────────────────────── activity_log 读 ──────────────────────────
def list_activity(target_id=None, target_type=None, limit=50) -> list:
    """读 activity_log（当前只有写没有读，此处补齐）。"""
    conn = _connect()
    try:
        where, params = [], []
        if target_id:
            where.append("target_id=?")
            params.append(target_id)
        if target_type:
            where.append("target_type=?")
            params.append(target_type)
        sql_where = ("WHERE " + " AND ".join(where)) if where else ""
        params.append(limit)
        rows = conn.execute(
            f"SELECT ts, actor, action, target_type, target_id, payload, execution_id FROM activity_log {sql_where} ORDER BY id DESC LIMIT ?",
            params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
            except Exception:
                pass
            result.append(d)
        return result
    finally:
        conn.close()


# ────────────────────────── next_actions（zcode 智能建议层）──────────────────────────
def sync_next_actions(actions: list, source="zcode") -> int:
    """全量快照同步 next_actions（删旧插新，单事务）。返回写入条数。

    actions 每项: {bid_id, label, skill?, playbook?, icon?, reason?}
    """
    ts = now_str()
    with DB_LOCK:
        conn = _connect()
        try:
            conn.execute("DELETE FROM next_actions")
            for a in actions:
                conn.execute(
                    "INSERT INTO next_actions (bid_id, skill, playbook, label, icon, reason, source, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (a.get("bid_id", ""), a.get("skill") or "", a.get("playbook") or "",
                     a.get("label", ""), a.get("icon", ""), a.get("reason", ""), source, ts))
            conn.commit()
        finally:
            conn.close()
    return len(actions)


def list_next_actions() -> dict:
    """全部 next_actions，按 bid_id 索引。"""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT bid_id, skill, playbook, label, icon, reason, source, updated_at FROM next_actions").fetchall()
        return {r["bid_id"]: dict(r) for r in rows}
    finally:
        conn.close()
