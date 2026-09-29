#!/usr/bin/env python3
"""app/services/command_engine.py · 统一命令执行引擎（自 server.py 1445-1462/2003-2151 迁移）

事务化 + 幂等（Idempotency-Key + Payload-Hash）+ 审计（command_execution / activity_log）。
审计库 = app.db；lead 类命令在同一事务内操作 app.db.leads；
bid 类命令经 bid_service → truth.db（跨库非原子，接受：bid 写自带事务 + 幂等键兜底重放）。
"""
import json
import sqlite3
import threading
import time
from datetime import datetime

from .. import config
from ..store import app_db

DB_LOCK = threading.RLock()
COMMAND_REGISTRY = {}


def register_command(command_id, scope, handler, description="", idempotent=True, schema=None):
    """注册命令。schema 为参数说明 dict（智能体能力发现 /api/v1/commands 暴露）。"""
    COMMAND_REGISTRY[command_id] = {
        "commandId": command_id,
        "scope": scope,
        "handler": handler,  # 签名: handler(conn, params) -> result
        "description": description,
        "idempotent": idempotent,
        "schema": schema or {},
    }


def registry_view():
    return [{"commandId": c["commandId"], "scope": c["scope"], "description": c["description"],
             "idempotent": c["idempotent"], "schema": c["schema"]}
            for c in COMMAND_REGISTRY.values()]


def _connect():
    conn = sqlite3.connect(str(config.APP_DB_PATH), timeout=15)
    conn.execute("PRAGMA busy_timeout=15000")
    conn.row_factory = sqlite3.Row
    return conn


def _lookup_idempotent(idempotency_key, payload_hash):
    """幂等查找:同 key 返原结果;同 key 但 hash 不同(双方都传)返 _conflict。"""
    try:
        with DB_LOCK:
            conn = _connect()
            row = conn.execute(
                "SELECT execution_id, payload_hash, result FROM command_execution WHERE idempotency_key=? AND status='completed' ORDER BY id DESC LIMIT 1",
                (idempotency_key,)).fetchone()
            conn.close()
        if not row:
            return None
        eid, ph, result = row
        if ph and payload_hash and ph != payload_hash:
            return {"_conflict": True, "execution_id": eid, "stored_hash": ph, "your_hash": payload_hash}
        try:
            result = json.loads(result)
        except Exception:
            pass
        return {"execution_id": eid, "result": result}
    except Exception:
        return None


def dispatch(command_id, params, idempotency_key=None, payload_hash=None, agent_id="duke", _internal=False):
    """统一命令执行。返回 (status_code, response_dict, execution_id)。"""
    cmd = COMMAND_REGISTRY.get(command_id)
    if not cmd:
        return 404, {"err": f"未知 commandId: {command_id}"}, None
    execution_id = f"cmd_{int(time.time()*1000)}_{hash(command_id+str(params))%10000:04d}"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 1. 幂等检查（有 key 就检查）
    if idempotency_key:
        existing = _lookup_idempotent(idempotency_key, payload_hash)
        if existing:
            if existing.get("_conflict"):
                return 409, {"err": "IDEMPOTENCY_PAYLOAD_MISMATCH", **existing}, existing["execution_id"]
            return 200, {"ok": True, "execution_id": existing["execution_id"], "commandId": command_id,
                         "result": existing["result"], "replay": True, "_replay": True}, existing["execution_id"]
    # 2. 事务化执行（try/finally 保证 conn 必 ROLLBACK + close，防 WAL 写锁泄漏）
    conn = None
    try:
        with DB_LOCK:
            conn = _connect()
            conn.execute("BEGIN")
            conn.execute(
                "INSERT INTO command_execution (execution_id, commandId, idempotency_key, payload_hash, agent_id, params, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'processing', ?)",
                (execution_id, command_id, idempotency_key or "", payload_hash or "",
                 agent_id, json.dumps(params, ensure_ascii=False), now))
            app_db.log_activity_in_conn(conn, agent_id, command_id, "command", command_id, params, execution_id)
            result = cmd["handler"](conn, params)
            if isinstance(result, dict) and result.get("err"):
                conn.execute(
                    "UPDATE command_execution SET status='failed', error=?, result=?, completed_at=? WHERE execution_id=?",
                    (result["err"], json.dumps(result, ensure_ascii=False),
                     datetime.now().strftime("%Y-%m-%d %H:%M:%S"), execution_id))
                conn.execute("COMMIT")
                return 400, result, execution_id
            completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE command_execution SET status='completed', result=?, completed_at=? WHERE execution_id=?",
                (json.dumps(result, ensure_ascii=False, default=str), completed_at, execution_id))
            conn.execute("COMMIT")
        return 200, {"ok": True, "execution_id": execution_id, "commandId": command_id, "result": result}, execution_id
    except Exception as e:
        try:
            with DB_LOCK:
                err_conn = _connect()
                err_conn.execute(
                    "UPDATE command_execution SET status='failed', error=?, completed_at=? WHERE execution_id=?",
                    (str(e), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), execution_id))
                err_conn.commit()
                err_conn.close()
        except Exception:
            pass
        return 500, {"err": f"执行异常: {e}", "execution_id": execution_id}, execution_id
    finally:
        if conn is not None:
            try:
                conn.execute("ROLLBACK")  # 已 COMMIT 的 conn 上是 no-op
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
