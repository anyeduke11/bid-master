#!/usr/bin/env python3
"""bid_master_mcp.py · bid-master MCP server（stdio · stdlib 零依赖 · DEV-0059）

让 ZCode（或任何 MCP 客户端）以原生工具方式操作 bid-master，替代散落的 curl/脚本记忆。

传输：stdio，换行分隔 JSON-RPC 2.0（MCP stdio 约定）。stdout 只走协议帧，日志全走 stderr。

安全边界（DEV-0059，经 Mimosa 两轮加固后定稿）：
  - 零直接网络/子进程原语：HTTP 全部走 rules/kanban_post.py（本机白名单 127.0.0.1:8080 +
    /api/v1/ 前缀校验）；阶段推进/材料复验走进程内 import rules/set_stage（与 CLI/看板同
    门禁同审计）；标讯抓取走看板 /api/v1/capture/run（服务负责子进程生命周期）；
  - 入参收口：bid_id ^[A-Za-z0-9._-]+$、to_stage 限 S0–S9 枚举、自由文本限长拒控制字符；
  - 看板服务未起时，走服务的工具报"先运行 start.sh"提示，只读真相层工具不受影响。

ZCode 注册（工作区级，自动连接）：<repo>/.zcode/config.json
  {"mcp": {"servers": {"bid-master": {"type": "stdio", "command": "<repo>/.venv/bin/python3",
    "args": ["<repo>/mcp/bid_master_mcp.py"], "cwd": "<repo>", "timeoutMs": 15000}}}}
"""
import io
import json
import os
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "rules"))

import kanban_post  # noqa: E402  本机白名单 HTTP 原语（get_json / post_json / post_command）

DATA_ROOT = Path(os.environ.get("BIDMASTER_HOME") or (Path.home() / ".bidmaster"))
SERVER_INFO = {"name": "bid-master", "version": "1.0.0"}

_BID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_STAGES = {f"S{i}" for i in range(10)}
_TEXT_CAP = 400  # 自由文本参数（sign_off / ignore_material / date 等）统一限长


def _bid(value) -> str:
    if not _BID_RE.fullmatch(str(value)):
        raise ValueError(f"bid_id 含非法字符：{value!r}")
    return str(value)


def _stage(value) -> str:
    v = str(value).strip().upper()
    if v not in _STAGES:
        raise ValueError(f"非法阶段：{value!r}（S0–S9）")
    return v


def _text(value, name: str) -> str:
    v = str(value or "").strip()
    if len(v) > _TEXT_CAP:
        raise ValueError(f"{name} 超长（>{_TEXT_CAP}）")
    if re.search(r"[<>{}\x00-\x08]", v):
        raise ValueError(f"{name} 含非法字符")
    return v


def _store():
    import store
    store.init()
    return store


def _set_stage_call(args: list[str]) -> dict:
    """进程内调 set_stage CLI（stdout 捕获为文本，避免污染 MCP 协议帧）。

    与 subprocess 版本同门禁同审计——advance_payload/settle_material 是 set_stage
    main() 的同一执行体，audit/gate_attempt/store 写入完全一致。
    """
    import set_stage as ss
    old = sys.argv
    sys.argv = ["set_stage.py"] + args
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = ss.main() or 0
    finally:
        sys.argv = old
    return {"rc": rc, "output": buf.getvalue().strip()[-2000:]}


# ────────────────────────── 工具实现（可被 bid CLI 导入复用） ──────────────────────────

def tool_bid_status(_: dict) -> dict:
    s = _store()
    funnel = s.read_funnel()
    rows = s._conn().execute(
        "SELECT ticket_id, type, status, bid_id, created_at FROM tickets WHERE status='generated' ORDER BY created_at DESC").fetchall()
    tickets = [{"ticket_id": r[0], "type": r[1], "status": r[2], "bid_id": r[3]} for r in rows]
    service = None
    try:
        service = kanban_post.get_json("/api/v1/health", timeout=2)
    except Exception:
        pass
    return {"funnel": {x["stage"]: x["count"] for x in funnel["stages"]},
            "total": funnel["total"], "epoch": funnel.get("epoch"),
            "service": service, "open_tickets": tickets}


def tool_bid_list(args: dict) -> dict:
    s = _store()
    bids = s.load_bids()
    stage = _text(args.get("stage"), "stage").upper() if args.get("stage") else ""
    if stage:
        bids = [b for b in bids if b.get("stage") == stage]
    return {"count": len(bids), "bids": [
        {"bid_id": b.get("bid_id"), "name": (b.get("name") or "")[:40], "stage": b.get("stage"),
         "priority": b.get("priority"), "updated_at": b.get("updated_at")} for b in bids]}


def tool_bid_show(args: dict) -> dict:
    return _store().read_bid_detail(_bid(args["bid_id"]))


def tool_bid_gate_probe(args: dict) -> dict:
    """只读门禁探针：推进到 to_stage 会卡在哪些检查（不写任何状态）。"""
    import set_stage
    bid_id, to_stage = _bid(args["bid_id"]), _stage(args["to_stage"])
    rec = next((r for r in set_stage._load_bids() if r.get("bid_id") == bid_id), None)
    if rec is None:
        return {"ok": False, "error": f"bid 不存在：{bid_id}"}
    cur = rec.get("stage", "S0")
    gate = set_stage.GATES.get((cur, to_stage))
    if gate is None:
        return {"ok": True, "from": cur, "to": to_stage, "note": "本迁移无门禁"}
    ok, blockers, extra = gate(DATA_ROOT / "bids" / bid_id,
                               {"sign_off": _text(args.get("sign_off"), "sign_off")})
    return {"ok": ok, "from": cur, "to": to_stage, "blockers": blockers, "extra": extra}


def tool_bid_advance(args: dict) -> dict:
    import set_stage as ss
    rc, payload = ss.advance_payload(_bid(args["bid_id"]), _stage(args["to_stage"]),
                                     _text(args.get("sign_off"), "sign_off"),
                                     _text(args.get("ignore_material"), "ignore_material"))
    return {"rc": rc, **payload}


def tool_bid_settle_material(args: dict) -> dict:
    import set_stage as ss
    return _set_stage_call(["--bid", _bid(args["bid_id"]), "--settle-material"])


def tool_ticket_list(args: dict) -> dict:
    sql = "SELECT ticket_id, type, status, bid_id, created_at FROM tickets"
    params: list = []
    if args.get("bid_id"):
        sql += " WHERE bid_id=?"
        params.append(_bid(args["bid_id"]))
    sql += " ORDER BY created_at DESC LIMIT 50"
    rows = _store()._conn().execute(sql, params).fetchall()
    return {"count": len(rows), "tickets": [
        {"ticket_id": r[0], "type": r[1], "status": r[2], "bid_id": r[3], "created_at": r[4]} for r in rows]}


def tool_lesson_list(_: dict) -> dict:
    s = _store()
    rows = s._conn().execute(
        "SELECT id, scenario, lesson, supersession, status FROM lessons WHERE status='active' ORDER BY id").fetchall()
    return {"count": len(rows), "lessons": [
        {"id": r[0], "scenario": r[1], "lesson": r[2], "supersession": r[3]} for r in rows]}


def tool_lead_list(args: dict) -> dict:
    limit = max(1, min(int(args.get("limit", 20)), 200))
    q = f"/api/v1/leads?limit={limit}"
    if args.get("phase"):
        from urllib.parse import quote
        q += "&phase=" + quote(_text(args["phase"], "phase"))
    d = kanban_post.get_json(q)
    leads = d.get("leads") or []
    return {"count": len(leads), "leads": [
        {k: l.get(k) for k in ("lead_id", "title", "buyer", "phase", "priority", "deadline", "link")} for l in leads]}


def tool_capture_run(args: dict) -> dict:
    """触发标讯抓取（走看板 /api/v1/capture/run，服务管理子进程生命周期）。

    dry 模式无服务依赖：直接读 capture 引擎 --dry 输出走子进程会被协议污染，
    故 dry 也经服务端点。服务未起时 kanban_post 报启动提示。
    """
    if args.get("dry"):
        # dry 只读预览：无服务依赖场景下允许直接跑引擎脚本（bash 脚本自身已过安全审查）
        raise ValueError("dry 预览请用 CLI：python3 scripts/lead_capture_crawl4ai.py --dry；MCP 触发真实抓取去掉 dry")
    resp = kanban_post.post_json("/api/v1/capture/run", {}, agent_id="mcp", timeout=15)
    return {"triggered": resp, "note": "抓取异步执行；数分钟后可用 lead_list 或看板 inbox 面板查看增量"}


def tool_digest(args: dict) -> dict:
    date = _text(args.get("date"), "date") if args.get("date") else ""
    if date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError(f"日期格式应为 YYYY-MM-DD：{date!r}")
    return kanban_post.get_json("/api/v1/digest" + (f"?date={date}" if date else ""))


def tool_kanban_command(args: dict) -> dict:
    return kanban_post.post_command({"commandId": _text(args["commandId"], "commandId"),
                                     "params": args.get("params") or {}},
                                    agent_id="mcp",
                                    idempotency_key=_text(args.get("idempotency_key"), "idempotency_key"))


# ────────────────────────── 工具注册表 ──────────────────────────

TOOLS = [
    ("bid_status", "总览：漏斗 S0-S9 分布、开放工单、看板服务健康（只读）", {"type": "object", "properties": {}}, tool_bid_status),
    ("bid_list", "标列表（可按 stage 过滤）（只读）",
     {"type": "object", "properties": {"stage": {"type": "string", "description": "如 S4/S5"}}, "required": []}, tool_bid_list),
    ("bid_show", "标详情：阶段史/产物登记/门禁尝试（只读）",
     {"type": "object", "properties": {"bid_id": {"type": "string"}}, "required": ["bid_id"]}, tool_bid_show),
    ("bid_gate_probe", "只读门禁探针：推进到目标阶段会被哪些检查拦（不写状态）",
     {"type": "object", "properties": {"bid_id": {"type": "string"}, "to_stage": {"type": "string", "description": "S3..S9"}},
      "required": ["bid_id", "to_stage"]}, tool_bid_gate_probe),
    ("bid_advance", "推进阶段（唯一写口 set_stage，带门禁；S5→S6 须 sign_off）",
     {"type": "object", "properties": {"bid_id": {"type": "string"}, "to_stage": {"type": "string"},
      "sign_off": {"type": "string", "description": "L3 人工签核姓名，S5→S6 必填"},
      "ignore_material": {"type": "string", "description": "S4→S5 素材率门禁忽略原因（可选）"}},
      "required": ["bid_id", "to_stage"]}, tool_bid_advance),
    ("bid_settle_material", "材料补齐复验销单（素材率≥80% 且零缺口 → 材料债工单 done）",
     {"type": "object", "properties": {"bid_id": {"type": "string"}}, "required": ["bid_id"]}, tool_bid_settle_material),
    ("ticket_list", "工单列表（gate/material，可按 bid 过滤）（只读）",
     {"type": "object", "properties": {"bid_id": {"type": "string"}}, "required": []}, tool_ticket_list),
    ("lesson_list", "活跃教训库（只读）", {"type": "object", "properties": {}}, tool_lesson_list),
    ("lead_list", "商机线索列表（走看板服务；可 phase 过滤）",
     {"type": "object", "properties": {"limit": {"type": "integer"}, "phase": {"type": "string", "description": "线索期/发标/投标/述标/公示/交付/回款"}},
      "required": []}, tool_lead_list),
    ("capture_run", "触发标讯抓取（走看板 capture 端点，异步执行；服务须在跑）",
     {"type": "object", "properties": {}, "required": []}, tool_capture_run),
    ("digest", "今日（或指定日）digest 摘要（走看板服务）",
     {"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD 可选"}}, "required": []}, tool_digest),
    ("kanban_command", "看板命令管道直通（bid.create/lead.qualify/collection.sync 等全部注册命令，可经 GET /api/v1/commands 枚举；走审计+幂等）",
     {"type": "object", "properties": {"commandId": {"type": "string"}, "params": {"type": "object"},
      "idempotency_key": {"type": "string"}}, "required": ["commandId"]}, tool_kanban_command),
]

TOOL_MAP = {name: fn for name, _, _, fn in TOOLS}


# ────────────────────────── MCP 协议层（stdio JSON-RPC 2.0） ──────────────────────────

def _result(msg_id, result):
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle(msg: dict) -> dict | None:
    method = msg.get("method", "")
    msg_id = msg.get("id")
    if msg_id is None:
        return None  # notification：initialized 等静默
    if method == "initialize":
        return _result(msg_id, {
            "protocolVersion": msg.get("params", {}).get("protocolVersion") or "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(msg_id, {"tools": [
            {"name": n, "description": d, "inputSchema": sc} for n, d, sc, _ in TOOLS]})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name", "")
        fn = TOOL_MAP.get(name)
        if fn is None:
            return _error(msg_id, -32602, f"未知工具：{name}")
        try:
            out = fn(params.get("arguments") or {})
            text = json.dumps(out, ensure_ascii=False, indent=1, default=str)
            return _result(msg_id, {"content": [{"type": "text", "text": text[:60000]}]})
        except Exception as e:  # 工具级错误按 MCP 约定走 isError 结果
            return _result(msg_id, {"content": [{"type": "text", "text": f"⛔ {type(e).__name__}: {e}"}],
                                    "isError": True})
    return _error(msg_id, -32601, f"未知方法：{method}")


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            print(json.dumps(_error(None, -32700, f"JSON 解析失败：{e}")), flush=True)
            continue
        try:
            resp = handle(msg)
        except Exception as e:
            resp = _error(msg.get("id"), -32603, f"内部错误：{type(e).__name__}: {e}")
        if resp is not None:
            print(json.dumps(resp, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
