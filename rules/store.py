#!/usr/bin/env python3
"""store.py · 真实层唯一写口（truth layer · v0.5.0）

设计依据：docs/truth-layer-plan.md
────────────────────────────────────────────────────────────────
真实层 = ~/.bidmaster/truth.db（SQLite WAL，权威状态：bids/stage_history/artifacts/lessons/tickets）
生产层 = bids/<id>/ 与 memory/ 的 llm-wiki 式文件产物（写后必须 register 才被承认）
唯一不变式：智能体经 skill 的脚本 API（本模块）写真实层；jsonl 降级为兼容导出。

安全：建表语句为纯静态字面量（无任何内嵌值/无用户输入）；一切数据读写只用 ? 占位参数绑定。
值约束（stage/kind）在写口以 Python 校验。
并发：写事务 BEGIN IMMEDIATE + busy_timeout=15s。
回退：truth.db 损坏 → 删库重跑 init（从 jsonl 单向导入）。
"""
import hashlib
import json
import os
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

# DEV-0042：数据根可经 BIDMASTER_HOME 环境变量覆盖（测试密封隔离用；生产默认 ~/.bidmaster）
DATA_ROOT = Path(os.environ.get("BIDMASTER_HOME") or (Path.home() / ".bidmaster"))
DB_PATH = DATA_ROOT / "truth.db"
JSONL = DATA_ROOT / "memory" / "bids.jsonl"
LESSONS_MD = DATA_ROOT / "memory" / "lessons.md"
STAGES = tuple(f"S{i}" for i in range(10))
# R7（工程审查 2026-09-19）：classified=涉密壳（元数据级跟踪，内容零入库）；显式 kind 由调用方传入，
# 自动判定走 kind_for()（bid_service/set_stage 共用，勿再内联 DEMO_MARKERS 判断）。
KINDS = ("real", "demo", "test", "classified")
DEMO_MARKERS = ("demo", "smoke", "probe", "kanban-demo", "w1t", "test")
_CTX = threading.local()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _conn() -> sqlite3.Connection:
    c = getattr(_CTX, "conn", None)
    if c is None:
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(DB_PATH), timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=15000")
        c.execute("PRAGMA foreign_keys=ON")
        _CTX.conn = c
    return c


def init() -> None:
    """建表（纯静态 DDL）；truth.db 空时从 jsonl 单向导入（demo 判 kind）。幂等。含轻量迁移。"""
    c = _conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS bids (
        bid_id TEXT PRIMARY KEY,
        stage TEXT NOT NULL,
        kind TEXT NOT NULL,
        bootstrapped INTEGER DEFAULT 0,
        note TEXT,
        created_at TEXT,
        updated_at TEXT);
    CREATE TABLE IF NOT EXISTS stage_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bid_id TEXT NOT NULL REFERENCES bids(bid_id),
        from_stage TEXT,
        to_stage TEXT NOT NULL,
        ts TEXT NOT NULL,
        sign_off TEXT,
        gate_ms INTEGER);
    CREATE TABLE IF NOT EXISTS artifacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bid_id TEXT NOT NULL REFERENCES bids(bid_id),
        kind TEXT NOT NULL,
        path TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        status TEXT NOT NULL,
        registered_at TEXT NOT NULL,
        producer TEXT);
    CREATE TABLE IF NOT EXISTS lessons (
        id TEXT PRIMARY KEY,
        scenario TEXT,
        lesson TEXT NOT NULL,
        supersession TEXT,
        status TEXT,
        created_at TEXT);
    CREATE TABLE IF NOT EXISTS tickets (
        ticket_id TEXT PRIMARY KEY,
        type TEXT,
        status TEXT,
        bid_id TEXT,
        created_at TEXT,
        executed_at TEXT,
        consumed_at TEXT);
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        agent TEXT,
        bid_id TEXT,
        model TEXT,
        duration_s INTEGER,
        input_fingerprint TEXT,
        ticket_id TEXT,
        self_check TEXT,
        tokens INTEGER,
        ts TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS gate_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bid_id TEXT NOT NULL,
        from_stage TEXT,
        to_stage TEXT NOT NULL,
        ok INTEGER NOT NULL,
        blockers TEXT,
        gate_ms INTEGER,
        actor TEXT,
        ts TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT);
    CREATE TABLE IF NOT EXISTS kb_assets (
        domain TEXT NOT NULL,
        id TEXT NOT NULL,
        name TEXT,
        file TEXT,
        fingerprint TEXT,
        sensitivity TEXT,
        valid_until TEXT,
        status TEXT,
        raw TEXT,
        updated_at TEXT,
        PRIMARY KEY (domain, id));
    """)
    # DEV-0042：bid_profile —— 看板运营字段（kanban 形状）入真实层，与 bids 表同库同写口。
    # data 列存完整 JSON（前端 24 字段超集形状）；冗余列仅供过滤/排序。
    c.executescript("""
    CREATE TABLE IF NOT EXISTS bid_profile (
        bid_id TEXT PRIMARY KEY REFERENCES bids(bid_id),
        data TEXT NOT NULL,
        lifecycle TEXT,
        priority TEXT,
        stage TEXT,
        industry TEXT,
        region TEXT,
        tier TEXT,
        est_amount REAL,
        closed_at TEXT,
        archived_at TEXT,
        updated_at TEXT);
    CREATE INDEX IF NOT EXISTS idx_bid_profile_lifecycle ON bid_profile(lifecycle);
    """)
    tcols = [r[1] for r in c.execute("PRAGMA table_info(tickets)")]
    if "dispatched_at" not in tcols:
        c.execute("ALTER TABLE tickets ADD COLUMN dispatched_at TEXT")
    # DEV-0042：artifacts.producer 列迁移（署名断点；旧库无此列）
    acols = [r[1] for r in c.execute("PRAGMA table_info(artifacts)")]
    if acols and "producer" not in acols:
        c.execute("ALTER TABLE artifacts ADD COLUMN producer TEXT")
    # kind 规范化迁移（幂等且即提交）：UPDATE 是 DML 会开隐式事务，必须显式收口，
    # 否则同连接后续 BEGIN IMMEDIATE 会报 "within a transaction"
    if c.execute("SELECT COUNT(*) AS n FROM artifacts WHERE kind=?", ("verify",)).fetchone()["n"]:
        with c:
            c.execute("UPDATE artifacts SET kind='verify_draft' WHERE kind='verify' AND path LIKE '%verify_draft%'")
            c.execute("UPDATE artifacts SET kind='verify_audit' WHERE kind='verify' AND path LIKE '%verify_audit%'")
            c.execute("UPDATE artifacts SET kind='locator' WHERE kind='verify' AND path LIKE '%locator%'")
    n = c.execute("SELECT COUNT(*) AS n FROM bids").fetchone()["n"]
    if n == 0 and JSONL.exists():
        _import_jsonl()


def _kind_of(bid_id: str, rec: dict) -> str:
    low = str(bid_id).lower()
    if any(m in low for m in DEMO_MARKERS):
        return "demo"
    if rec.get("bootstrapped") and "demo" in str(rec.get("note", "")).lower():
        return "demo"
    return "real"


def kind_for(bid_id: str, bootstrapped: bool = False, note: str = "") -> str:
    """kind 自动判定唯一入口（R7 去重：bid_service.create / set_stage.bootstrap 原各持一份内联逻辑）。
    仅返回 real/demo；显式 kind（如 classified）不经过本函数——调用方校验 KINDS 后直接透传 create_bid。"""
    return _kind_of(bid_id, {"bootstrapped": bootstrapped, "note": note})


def _import_jsonl() -> int:
    rows = [json.loads(l) for l in JSONL.read_text(encoding="utf-8").splitlines() if l.strip()]
    c = _conn()
    with c:
        for r in rows:
            bid = r.get("bid_id")
            stage = r.get("stage") if r.get("stage") in STAGES else "S0"
            c.execute("INSERT OR IGNORE INTO bids (bid_id, stage, kind, bootstrapped, note, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                      (bid, stage, _kind_of(bid, r), 1 if r.get("bootstrapped") else 0,
                       str(r.get("note", ""))[:200], r.get("updated_at", _now()), r.get("updated_at", _now())))
            for h in r.get("stage_history") or []:
                c.execute("INSERT INTO stage_history (bid_id, from_stage, to_stage, ts, sign_off, gate_ms) VALUES (?,?,?,?,?,?)",
                          (bid, h.get("from"), h.get("to"), h.get("ts", _now()), h.get("sign_off"), h.get("gate_ms")))
    return len(rows)


def export_jsonl() -> None:
    """兼容导出（v1.0 起已退役停更：读方全部切 truth.db）。保留函数防旧调用方报错。"""
    pass


# ────────────────────────── 读 API（参数绑定） ──────────────────────────
def load_bids(kind: str | None = None) -> list:
    c = _conn()
    if kind:
        return [dict(r) for r in c.execute("SELECT * FROM bids WHERE kind=? ORDER BY bid_id", (kind,))]
    return [dict(r) for r in c.execute("SELECT * FROM bids ORDER BY bid_id")]


def get_bid(bid_id: str) -> dict | None:
    r = _conn().execute("SELECT * FROM bids WHERE bid_id=?", (bid_id,)).fetchone()
    return dict(r) if r else None


def load_normalized() -> list:
    """bids_consistency 兼容读口：真实层读，字段与旧 normalize 对齐。"""
    rows = []
    for b in load_bids():
        b.setdefault("schema", "baw-1")
        b["stage_history"] = [dict(h) for h in _conn().execute(
            "SELECT from_stage AS 'from', to_stage AS 'to', ts, sign_off, gate_ms FROM stage_history WHERE bid_id=? ORDER BY id", (b["bid_id"],))]
        rows.append(b)
    return rows


# ────────────────────────── 写 API（唯一写口，值校验+参数绑定） ──────────────────────────
def create_bid(bid_id: str, stage: str, bootstrapped: bool = False, note: str = "", kind: str = "real") -> dict:
    if stage not in STAGES:
        raise ValueError(f"非法 stage: {stage}")
    if kind not in KINDS:
        raise ValueError(f"非法 kind: {kind}")
    c = _conn()
    with c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT INTO bids (bid_id, stage, kind, bootstrapped, note, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                  (bid_id, stage, kind, 1 if bootstrapped else 0, note, _now(), _now()))
        c.execute("INSERT INTO stage_history (bid_id, from_stage, to_stage, ts, sign_off) VALUES (?,?,?,?,?)",
                  (bid_id, None, stage, _now(), None))
        _bump_epoch(c)
    export_jsonl()
    return {"ok": True, "bid_id": bid_id, "stage": stage}


def set_stage(bid_id: str, to_stage: str, from_stage: str | None, sign_off: str | None, gate_ms: int) -> None:
    if to_stage not in STAGES:
        raise ValueError(f"非法 stage: {to_stage}")
    c = _conn()
    with c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("UPDATE bids SET stage=?, updated_at=? WHERE bid_id=?", (to_stage, _now(), bid_id))
        c.execute("INSERT INTO stage_history (bid_id, from_stage, to_stage, ts, sign_off, gate_ms) VALUES (?,?,?,?,?,?)",
                  (bid_id, from_stage, to_stage, _now(), sign_off, gate_ms))
    export_jsonl()


# ────────────────────────── bid_profile（DEV-0042 · 看板运营字段入真实层） ──────────────────────────
def upsert_bid_profile(bid_id: str, data: dict) -> None:
    """看板运营字段整包落库（data 为前端 24 字段形状 JSON；冗余列供过滤排序）。
    全参数化 SQL（先查后插/改，SQL 全字面量），无任何字符串拼接。"""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    c = _conn()
    with c:
        c.execute("BEGIN IMMEDIATE")
        exists = c.execute("SELECT 1 FROM bid_profile WHERE bid_id=?", (bid_id,)).fetchone()
        if exists:
            c.execute("UPDATE bid_profile SET data=?, lifecycle=?, priority=?, stage=?, industry=?, region=?, tier=?, est_amount=?, closed_at=?, archived_at=?, updated_at=? WHERE bid_id=?",
                      (payload, data.get("lifecycle", "active"), data.get("priority", ""), data.get("stage", ""),
                       data.get("industry", ""), data.get("region", ""), data.get("tier", ""),
                       float(data.get("est_amount", 0) or 0),
                       data.get("closed_at", ""), data.get("archived_at", ""),
                       data.get("updated_at", _now()), bid_id))
        else:
            c.execute("INSERT INTO bid_profile (bid_id, data, lifecycle, priority, stage, industry, region, tier, est_amount, closed_at, archived_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (bid_id, payload, data.get("lifecycle", "active"), data.get("priority", ""), data.get("stage", ""),
                       data.get("industry", ""), data.get("region", ""), data.get("tier", ""),
                       float(data.get("est_amount", 0) or 0),
                       data.get("closed_at", ""), data.get("archived_at", ""),
                       data.get("updated_at", _now())))
        _bump_epoch(c)  # DEV-0081：profile 变更也产生镜子刷新信号


def get_bid_profile(bid_id: str) -> dict | None:
    r = _conn().execute("SELECT bid_id, data FROM bid_profile WHERE bid_id=?", (bid_id,)).fetchone()
    if not r:
        return None
    d = json.loads(r["data"])
    d.setdefault("code", r["bid_id"])
    return d


def list_bid_profiles() -> list:
    return [json.loads(r["data"]) for r in _conn().execute("SELECT data FROM bid_profile ORDER BY bid_id")]


def delete_bid(bid_id: str) -> bool:
    """删除标（profile + bids + 关联 history/artifacts/gate_attempts）。看板 bid.delete 用。"""
    c = _conn()
    with c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("DELETE FROM bid_profile WHERE bid_id=?", (bid_id,))
        c.execute("DELETE FROM stage_history WHERE bid_id=?", (bid_id,))
        c.execute("DELETE FROM artifacts WHERE bid_id=?", (bid_id,))
        c.execute("DELETE FROM gate_attempts WHERE bid_id=?", (bid_id,))
        cur = c.execute("DELETE FROM bids WHERE bid_id=?", (bid_id,))
        _bump_epoch(c)  # DEV-0081：删标产生镜子刷新信号
    return cur.rowcount > 0


# 契约 kind → schema 名（register_artifact 按此校验；未列出的 kind 跳过校验并记 warn）
_CONTRACT_KINDS = {"stage0": "stage0", "hits_recon": "hits_recon", "completeness": "completeness",
                   "spec": "spec", "audit": "audit", "locator": "locator"}


def register_artifact(bid_id: str, kind: str, path: str, status: str = "registered",
                      producer: str = "main-agent") -> dict:
    """生产层产物登记：契约校验（P1-1）→ 指纹复算 → 落库。
    状态机（P1-2）：生产者不得自报 final——机检/门禁类产物一律存 registered，由门禁提升。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    if kind in _CONTRACT_KINDS:
        import contract_util
        errs = contract_util.validate_kind(_CONTRACT_KINDS[kind], json.loads(p.read_text(encoding="utf-8")))
        if errs:
            raise ValueError(f"契约校验失败（{kind}）：{errs[:3]}")
    stored_status = "registered" if status == "final" else status
    fp = "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
    c = _conn()
    with c:
        c.execute("INSERT INTO artifacts (bid_id, kind, path, fingerprint, status, registered_at, producer) VALUES (?,?,?,?,?,?,?)",
                  (bid_id, kind, str(p), fp, stored_status, _now(), producer))
        _bump_epoch(c)  # DEV-0081：产物登记产生镜子刷新信号
    return {"ok": True, "fingerprint": fp, "status": stored_status}


def promote_artifact(bid_id: str, kind: str, path: str) -> dict:
    """门禁提升：registered → final（生产者不得自报 final，P1-2）。指纹未变才提升。"""
    c = _conn()
    row = c.execute("SELECT id, fingerprint, path FROM artifacts WHERE bid_id=? AND kind=? AND path=? ORDER BY id DESC",
                    (bid_id, kind, str(path))).fetchone()
    if not row:
        return {"ok": False, "err": "未找到登记记录"}
    import hashlib
    cur_fp = "sha256:" + hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest()
    if cur_fp != row["fingerprint"]:
        return {"ok": False, "err": f"指纹已变（产物被改动），拒绝提升：{row['path']}"}
    with c:
        c.execute("UPDATE artifacts SET status='final' WHERE id=?", (row["id"],))
    return {"ok": True, "status": "final", "fingerprint": row["fingerprint"]}


def latest_artifact(bid_id: str, kind: str) -> dict | None:
    """门禁读口（P1-2）：取该 bid+kind 最新登记的产物行。"""
    r = _conn().execute("SELECT * FROM artifacts WHERE bid_id=? AND kind=? ORDER BY id DESC LIMIT 1",
                        (bid_id, kind)).fetchone()
    return dict(r) if r else None


def list_artifacts(bid_id: str, kind: str | None = None) -> list:
    c = _conn()
    if kind:
        return [dict(r) for r in c.execute("SELECT * FROM artifacts WHERE bid_id=? AND kind=? ORDER BY id", (bid_id, kind))]
    return [dict(r) for r in c.execute("SELECT * FROM artifacts WHERE bid_id=? ORDER BY id", (bid_id,))]


def _bump_epoch(c: sqlite3.Connection) -> None:
    """epoch 递增（一致性协议 L2 变更信号）。
    R3：create_bid / upsert_ticket / record_gate_attempt bump；
    DEV-0081 补全：upsert_bid_profile / register_artifact / delete_bid 也 bump——
    看板内编辑 profile、登记产物、删标此前不产生信号，已打开的镜子不刷新。"""
    c.execute("INSERT INTO meta (key, value) VALUES ('epoch', '0') ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)")


def record_gate_attempt(bid_id: str, from_stage: str, to_stage: str, ok: bool,
                        blockers: list, gate_ms: int, actor: str | None) -> None:
    """门禁尝试结构化落库（P1-3）：看板卡点面板/通过率聚合的数据源。"""
    c = _conn()
    with c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT INTO gate_attempts (bid_id, from_stage, to_stage, ok, blockers, gate_ms, actor, ts) VALUES (?,?,?,?,?,?,?,?)",
                  (bid_id, from_stage, to_stage, 1 if ok else 0, json.dumps(blockers, ensure_ascii=False), gate_ms, actor, _now()))
        _bump_epoch(c)


def get_epoch() -> int:
    """一致性协议 L2（增补件 §5.3）：数据变更版本号。写口 bump，读方比对。"""
    c = _conn()
    r = c.execute("SELECT value FROM meta WHERE key=?", ("epoch",)).fetchone()
    return int(r["value"]) if r else 0


def register_run(agent: str, bid_id: str | None, model: str = "", duration_s: int | None = None,
                 input_fingerprint: str | None = None, ticket_id: str | None = None,
                 self_check: str | None = None, tokens: int | None = None) -> dict:
    """run manifest 入库（acceptance G2 / 看板 System 层数据源）。工单回执的权威来源。"""
    # DEV-0041：run_id 加 4 位随机尾——同一秒内同 agent 批量登记（编排器逐工位回写）不再撞 UNIQUE
    run_id = f"run_{datetime.now().strftime('%Y%m%d%H%M%S')}_{hashlib.sha256(f'{agent}{bid_id}{_now()}{os.urandom(8).hex()}'.encode()).hexdigest()[:12]}"
    c = _conn()
    with c:
        c.execute("INSERT INTO runs (run_id, agent, bid_id, model, duration_s, input_fingerprint, ticket_id, self_check, tokens, ts) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (run_id, agent, bid_id, model, duration_s, input_fingerprint, ticket_id, self_check, tokens, _now()))
    return {"ok": True, "run_id": run_id}


def upsert_lesson(lesson_id: str, scenario: str, lesson: str, supersession: str = "无") -> None:
    c = _conn()
    with c:
        c.execute("INSERT OR REPLACE INTO lessons (id, scenario, lesson, supersession, status, created_at) VALUES (?,?,?,?,?,?)",
                  (lesson_id, scenario, lesson, supersession, "active", _now()))


def lesson_exists(lesson_id: str) -> bool:
    return _conn().execute("SELECT 1 FROM lessons WHERE id=?", (lesson_id,)).fetchone() is not None


def upsert_ticket(ticket_id: str, ttype: str, status: str, bid_id: str | None) -> None:
    c = _conn()
    with c:
        c.execute("INSERT OR REPLACE INTO tickets (ticket_id, type, status, bid_id, created_at) VALUES (?,?,?,?,?)",
                  (ticket_id, ttype, status, bid_id, _now()))
        _bump_epoch(c)


# ────────────────────────── lessons 表权威化（P3'-2） ──────────────────────────
def import_lessons_from_md() -> int:
    """lessons.md → lessons 表（一次性导入；表非空则跳过）。解析 L-* 条目行。"""
    if not LESSONS_MD.exists():
        return 0
    c = _conn()
    if c.execute("SELECT COUNT(*) AS n FROM lessons").fetchone()["n"]:
        return 0
    text = LESSONS_MD.read_text(encoding="utf-8")
    section = ""
    n = 0
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        m = re.match(r"-\s*(L-\d+)（([^）]*)）(.+?)(?:\s*supersession:\s*(\S+))?\s*$", line)
        if not m:
            continue
        lid, date, body, sup = m.groups()
        with c:
            c.execute("INSERT OR IGNORE INTO lessons (id, scenario, lesson, supersession, status, created_at) VALUES (?,?,?,?,?,?)",
                      (lid, section, body.strip(), sup or "无", "active", date))
        n += 1
    return n


def export_lessons_md() -> None:
    """lessons 表 → lessons.md 渲染（llm-wiki 可读层；DB 是权威）。"""
    c = _conn()
    rows = [dict(r) for r in c.execute("SELECT * FROM lessons ORDER BY id")]
    h = ["# bid-master 迭代教训（BAW 权威层导出 · 表 lessons 渲染）",
         "",
         "> 协议：开工先通读（S2→S3 门禁校验 lessons_applied 引用 L-* 有效性）；",
         "> 新教训必须带 supersession（取代旧 ID，无则写'无'）；本文件为 lessons 表的导出渲染，勿手改。",
         ""]
    cur_section = None
    for r in rows:
        if r["scenario"] != cur_section:
            cur_section = r["scenario"]
            h.append("## " + (cur_section or "未分组"))
            h.append("")
        h.append(f"- {r['id']}（{(r['created_at'] or '')[:10]}）{r['lesson']} supersession: {r['supersession']}")
    LESSONS_MD.write_text("\n".join(h) + "\n", encoding="utf-8")


def next_lesson_id() -> str:
    c = _conn()
    ids = [int(str(m)[2:]) for (m,) in c.execute("SELECT id FROM lessons WHERE id LIKE 'L-%'")]
    return f"L-{(max(ids) + 1) if ids else 1}"


# ────────────────────────── kb_assets（P3'-1） ──────────────────────────
def upsert_kb_asset(domain: str, asset: dict) -> None:
    """kb 资产登记/更新（domain: certs/people/cases/solutions/bids_history）。"""
    c = _conn()
    with c:
        c.execute("INSERT OR REPLACE INTO kb_assets (domain, id, name, file, fingerprint, sensitivity, valid_until, status, raw, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (domain, str(asset.get("id", "")), str(asset.get("name", asset.get("title", "")))[:120],
                   str(asset.get("file", "")), str(asset.get("fingerprint", "")),
                   str(asset.get("sensitivity", "L2")), str(asset.get("valid_until") or asset.get("valid_until_", "") or ""),
                   str(asset.get("status", "")), json.dumps(asset, ensure_ascii=False), _now()))


def kb_assets_by_domain(domain: str) -> list:
    return [dict(r) for r in _conn().execute(
        "SELECT * FROM kb_assets WHERE domain=? ORDER BY id", (domain,))]


def stats() -> dict:
    c = _conn()
    return {
        "bids": c.execute("SELECT COUNT(*) AS n FROM bids").fetchone()["n"],
        "artifacts": c.execute("SELECT COUNT(*) AS n FROM artifacts").fetchone()["n"],
        "lessons": c.execute("SELECT COUNT(*) AS n FROM lessons").fetchone()["n"],
        "tickets": c.execute("SELECT COUNT(*) AS n FROM tickets").fetchone()["n"],
    }


# ────────────────────────── 读模型（P2 · 看板四问视图，只读） ──────────────────────────
def _mirror_rows(c) -> list:
    """镜子行（R3）：全部标 ×（kind, lifecycle, stage, profile JSON）。profile 缺失（纯 bootstrap 标）→ data=None。
    死线/复盘两类派生项共用——排除规则统一在这里：kind=demo 排除，lifecycle closed/archived 排除
    （防已结束标产出永久噪音，训练用户无视今日必办）。"""
    rows = []
    q = "SELECT b.bid_id AS bid_id, b.kind AS kind, b.stage AS stage, p.data AS data, COALESCE(p.lifecycle, 'active') AS lc FROM bids b LEFT JOIN bid_profile p ON b.bid_id = p.bid_id"
    for r in c.execute(q):
        if r["kind"] == "demo" or r["lc"] in ("closed", "archived"):
            continue
        rows.append({"bid_id": r["bid_id"], "data": r["data"], "stage": r["stage"]})
    return rows


def _scan_deadlines(rows: list) -> list:
    """死线扫描（R3）：bid_profile.due_at 分层 overdue(<0)/today(0)/soon(1-7)。
    容错：due_at 缺失/"持续"/脏格式 → 无死线项，不崩（坏数据静默降级，镜子不碎）。"""
    from datetime import date as _date, datetime as _dt
    today = _date.today()
    items = []
    for row in rows:
        if not row["data"]:
            continue
        try:
            data = json.loads(row["data"])
        except (TypeError, ValueError):
            continue
        raw = str(data.get("due_at", "") or "").strip()
        if not raw or raw == "持续":
            continue
        try:
            due = _dt.strptime(raw.split()[0], "%Y-%m-%d").date()
        except (ValueError, IndexError):
            continue
        days = (due - today).days
        if days > 7:
            continue
        sev = "overdue" if days < 0 else ("today" if days == 0 else "soon")
        label = "已逾期" if days < 0 else ("今日截止" if days == 0 else f"{days} 天后截止")
        items.append({"kind": "deadline", "bid_id": row["bid_id"], "due_at": raw,
                      "days_left": days, "severity": sev,
                      "detail": f"{label}：{data.get('client') or row['bid_id']}"})
    return items


def _scan_retro(c, rows: list) -> list:
    """S7 复盘派生提醒（R3，替代 reminder 工单）：stage==S7 且停留 >1 天 → 今日必办项；
    >7 天降级 stale（防永久噪音）；stage 离开 S7 自消（零写入、零 launchd 作业、存量 S7 标即覆盖）。
    DEV-0084 修复：原实现只查「进过 S7 且超 1 天」，从不查当前阶段——离开 S7 后提醒永久滞留
    （docstring 承诺与实现名实分离；本单 S7→S8 推进后提醒仍亮，实测抓到）。"""
    from datetime import datetime as _dt
    now = _dt.now().astimezone()
    items = []
    for row in rows:
        if row.get("stage") != "S7":
            continue
        r = c.execute("SELECT MAX(ts) AS s7_since FROM stage_history WHERE bid_id=? AND to_stage=?", (row["bid_id"], "S7")).fetchone()
        if not r or not r["s7_since"]:
            continue
        try:
            since = _dt.fromisoformat(str(r["s7_since"]))
        except ValueError:
            continue
        days = (now - since).days
        if days < 1:
            continue
        items.append({"kind": "retro_due", "bid_id": row["bid_id"],
                      "days_in_s7": days, "severity": "normal" if days <= 7 else "stale",
                      "detail": f"开标已过 {days} 天，复盘未启动（S7 停留中）"})
    return items


def read_now() -> dict:
    """今日必办：未消工单 + 近 7 天门禁失败 + alerts 告警 + 死线/复盘派生项（R3 镜子性）。"""
    import json as _json
    items = []
    c = _conn()
    for r in c.execute("SELECT ticket_id, type, bid_id, status, created_at FROM tickets WHERE status IN (?,?,?) ORDER BY created_at",
                       ("generated", "dispatched", "executed")):
        items.append({"kind": "ticket", "id": r["ticket_id"], "type": r["type"],
                      "bid_id": r["bid_id"], "status": r["status"], "since": r["created_at"]})
    # DEV-0041 可监测性：Python 侧按（bid+迁移）取最新一次失败去重——
    # 避免回归测试的拦截洪流把真实标的门禁拦截挤出 LIMIT 窗口（2026-09-12 实战发现的 Now 盲区根因）。
    seen_transitions = set()
    gate_items = []
    for r in c.execute("SELECT id, bid_id, from_stage, to_stage, ts, blockers FROM gate_attempts WHERE ok=0 AND ts >= datetime('now','-7 days') ORDER BY id DESC LIMIT 200"):
        key = (r["bid_id"], r["from_stage"], r["to_stage"])
        if key in seen_transitions:
            continue
        seen_transitions.add(key)
        try:
            blockers = json.loads(r["blockers"] or "[]")
        except Exception:
            blockers = []
        gate_items.append({"kind": "gate_blocked", "id": "gate-" + str(r["id"]), "bid_id": r["bid_id"],
                      "transition": str(r["from_stage"]) + "→" + str(r["to_stage"]),
                      "blockers": blockers[:3], "since": r["ts"]})
        if len(gate_items) >= 40:
            break
    items.extend(gate_items)
    # R3 镜子性派生项：死线（bid_profile.due_at）+ 开标复盘提醒（S7 停留）。
    # 两类均为墙钟驱动（跨天变化、零写入）——前端今日必办须配合 5s 无条件重渲染（T5）。
    _rows = _mirror_rows(c)
    items.extend(_scan_deadlines(_rows))
    items.extend(_scan_retro(c, _rows))
    alerts_p = DATA_ROOT / "alerts.json"
    if alerts_p.exists():
        try:
            for a in _json.loads(alerts_p.read_text(encoding="utf-8")).get("alerts", []):
                items.append({"kind": "alert", "severity": a.get("severity"),
                              "detail": a.get("detail", a.get("name", ""))})
        except Exception:
            pass
    return {"epoch": get_epoch(), "items": items, "count": len(items)}


def read_funnel() -> dict:
    """管线漏斗：S0–S9 各态数量。"""
    counts = {}
    for b in load_bids():
        st = b.get("stage", "S0")
        counts[st] = counts.get(st, 0) + 1
    stages = [{"stage": "S" + str(i), "count": counts.get("S" + str(i), 0)} for i in range(10)]
    # DEV-0041：漏斗补 epoch（与 now/bid 读模型对齐，前端顶栏 epoch 显示的数据源之一）
    return {"stages": stages, "total": sum(counts.values()), "epoch": get_epoch()}


def read_bid_detail(bid_id: str) -> dict:
    """单标深潜：状态/历史/门禁尝试/登记产物/verify 报告摘要。"""
    b = get_bid(bid_id)
    if not b:
        return {"error": "bid 不存在: " + str(bid_id)}
    c = _conn()
    history = [dict(r) for r in c.execute(
        "SELECT from_stage, to_stage, ts, sign_off, gate_ms FROM stage_history WHERE bid_id=? ORDER BY id", (bid_id,))]
    attempts = []
    for r in c.execute("SELECT id, from_stage, to_stage, ok, blockers, gate_ms, ts, actor FROM gate_attempts WHERE bid_id=? ORDER BY id DESC LIMIT 20",
                       (bid_id,)):
        a = dict(r)
        try:
            a["blockers"] = json.loads(a["blockers"] or "[]")
        except Exception:
            a["blockers"] = []
        attempts.append(a)
    artifacts = [dict(r) for r in c.execute(
        "SELECT kind, path, status, fingerprint, registered_at, producer FROM artifacts WHERE bid_id=? ORDER BY id DESC", (bid_id,))]
    verifies = []
    for a in artifacts:
        if a["kind"] not in ("verify_draft", "verify_audit", "locator"):
            continue
        p = Path(a["path"])
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        verifies.append({"kind": a["kind"], "path": a["path"], "value": d.get("pass", d.get("hit_rate"))})
    return {"bid_id": bid_id, "stage": b.get("stage"), "note": b.get("note", ""),
            "stage_history": history, "gate_attempts": attempts,
            "artifacts": artifacts, "verify_summary": verifies}


def read_system() -> dict:
    """Agent 运行时面板：名册 + runs 聚合 + gate 通过率 + 工单三态。"""
    import json as _json
    c = _conn()
    agents = []
    ca = Path(__file__).resolve().parent.parent / "contracts" / "agents"
    for p in sorted(ca.glob("*.json")) if ca.exists() else []:
        try:
            d = _json.loads(p.read_text(encoding="utf-8"))
            agents.append({"name": d.get("name"), "model": d.get("model"),
                           "readonly": d.get("readonly", False)})
        except Exception:
            continue
    runs_agg = [dict(r) for r in c.execute(
        "SELECT agent, COUNT(*) AS runs, COALESCE(SUM(tokens),0) AS tokens FROM runs GROUP BY agent ORDER BY runs DESC")]
    gate = []
    for r in c.execute("SELECT from_stage, to_stage, COUNT(*) AS attempts, SUM(ok) AS passed FROM gate_attempts GROUP BY from_stage, to_stage"):
        g = dict(r)
        g["gate"] = str(g["from_stage"]) + "→" + str(g["to_stage"])
        gate.append(g)
    tickets = [dict(r) for r in c.execute("SELECT status, COUNT(*) AS n FROM tickets GROUP BY status")]
    return {"agents": agents, "runs_by_agent": runs_agg,
            "runs_total": sum(r["runs"] for r in runs_agg),
            "tokens_total": sum(r["tokens"] for r in runs_agg),
            "gate_stats": gate, "tickets": tickets}


def main() -> int:
    init()
    c = _conn()
    real = c.execute("SELECT COUNT(*) AS n FROM bids WHERE kind=?", ("real",)).fetchone()["n"]
    demo = c.execute("SELECT COUNT(*) AS n FROM bids WHERE kind=?", ("demo",)).fetchone()["n"]
    print(f"truth.db：real={real} demo={demo}；{stats()}")
    for b in load_bids():
        print(f"  {b['bid_id']:<26} {b['stage']} {b['kind']}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
