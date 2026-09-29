#!/usr/bin/env python3
"""test_api.py · HTTP API v1 契约测试（make gate-api 挂载，DEV-0042）

定位：新 API 面（/api/v1）的可执行规格。逐端点断言「前端消费的字段名与类型」
（契约矩阵 docs/api-contract-matrix.md 是唯一基准）+ 智能体协议（X-Agent-Id 审计 /
幂等重放 / artifact.register 强制降级 / 门禁阻塞查询）。

隔离：全程密封——BIDMASTER_HOME 指向临时目录（truth.db/app.db/leads 全在临时区），
BID_BOARD_SKIP_REACH=1 关闭真实可达性探测。服务进程内起（ThreadingHTTPServer, port=0）。
运行：python3 tests/test_api.py；退出 0=全过。

SSRF 约束：客户端不构造 URL——直接 http.client 连接常量主机 127.0.0.1（被测服务自身），
端口仅接受 1-65535 的 int，请求路径必须以 /api/ 开头，无任何外部输入参与主机/协议构造。
"""
import http.client
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_TMP = Path(tempfile.mkdtemp(prefix="bidmaster-api-test-"))
os.environ["BIDMASTER_HOME"] = str(_TMP)
os.environ["BID_BOARD_SKIP_REACH"] = "1"
os.environ["BIDBOARD_EMPTY"] = "1"          # 密封测试不造 demo 假标
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "rules"))

RESULTS = []
HOST = "127.0.0.1"                          # 常量：被测服务只可能是本机环回


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


class Client:
    """极简 HTTP 测试客户端（标准库 http.client，固定环回目标）。"""

    def __init__(self, port):
        port = int(port)
        if not (0 < port < 65536):
            raise ValueError(f"port out of range: {port}")
        self.port = port

    def request(self, method, path, body=None, headers=None):
        if not path.startswith("/api/"):
            raise ValueError(f"test client only allows /api paths, got {path!r}")
        conn = http.client.HTTPConnection(HOST, self.port, timeout=35)
        try:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
            h = {"Content-Type": "application/json; charset=utf-8"}
            h.update(headers or {})
            conn.request(method, path, body=payload, headers=h)
            r = conn.getresponse()
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
        finally:
            conn.close()

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body=None, headers=None):
        return self.request("POST", path, body or {}, headers)

    def cmd(self, command_id, params, key=None, agent=None, payload_hash=None):
        import uuid as _uuid
        h = {"Idempotency-Key": key or f"t-{command_id}-{_uuid.uuid4().hex[:8]}"}
        if agent:
            h["X-Agent-Id"] = agent
        if payload_hash:
            h["Payload-Hash"] = payload_hash
        return self.post("/api/v1/commands", {"commandId": command_id, "params": params}, h)


def _keys(d):
    return set(d.keys()) if isinstance(d, dict) else set()


def main() -> int:
    import app.main as app_main
    srv = app_main.create_server(host="127.0.0.1", port=0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    c = Client(port)

    # ── ① 基础读端点（形状断言：契约矩阵 §一.读） ──
    st, health = c.get("/api/v1/health")
    check("health 200 + ok/service", st == 200 and health.get("ok") is True and "service" in health)
    st, init = c.get("/api/v1/initial")
    check("initial 200 + 五聚合键",
          st == 200 and {"bids", "stats", "events", "playbooks", "flow_template"} <= _keys(init),
          f"keys={sorted(_keys(init))}")
    st, stats = c.get("/api/v1/stats")
    check("stats 形状（total/p0/p1/p2/ready/blocked/total_ai/ready_rate）",
          st == 200 and {"total", "p0", "p1", "p2", "ready", "blocked", "total_ai", "ready_rate"} <= _keys(stats))
    st, bids = c.get("/api/v1/bids")
    check("bids 200", st == 200)
    st, epoch = c.get("/api/v1/epoch")
    check("epoch {ok, epoch:int}", st == 200 and epoch.get("ok") is True and isinstance(epoch.get("epoch"), int))
    st, alerts = c.get("/api/v1/alerts")
    check("alerts {ok, alerts:list}", st == 200 and alerts.get("ok") is True and isinstance(alerts.get("alerts"), list))
    for name in ("now", "funnel", "system"):
        st, v = c.get(f"/api/v1/views/{name}")
        check(f"views/{name} {{ok, view, data}}", st == 200 and v.get("ok") is True and v.get("view") == name and "data" in v)
    st, pl = c.get("/api/v1/playbooks")
    check("playbooks 200 且每项有 name", st == 200 and isinstance(pl, list) and all("name" in p for p in pl))
    st, sk = c.get("/api/v1/skills/status")
    check("skills/status 200", st == 200)
    st, cl = c.get("/api/v1/commands")
    check("commands 注册表 {commands:[...]} 且每项含 commandId/schema（能力发现）",
          st == 200 and isinstance(cl.get("commands"), list) and len(cl["commands"]) > 0
          and all("commandId" in cmd and "schema" in cmd for cmd in cl["commands"]))

    # ── ② bid 域：创建 + 超集形状（看板字段 ∪ BAW 字段，契约矩阵 §三.读） ──
    st, r = c.cmd("bid.create", {"code": "2026-api-selftest", "name": "API 契约自测标",
                                 "client": "测试客户A", "industry": "网络安全", "region": "深圳"},
                  key="t-bid-create-1", agent="api-test")
    check("bid.create 命令成功", st == 200 and r.get("ok") is True, str(r)[:120])
    st, detail = c.get("/api/v1/bids/2026-api-selftest")
    superset_kanban = {"code", "client", "stage", "priority", "ai_ready", "human_todo", "updated_at"}
    superset_baw = {"bid_id", "stage", "kind"}
    check("bid 详情超集形状（看板字段 ∪ BAW 字段）",
          st == 200 and superset_kanban <= _keys(detail) and superset_baw <= _keys(detail),
          f"keys={sorted(_keys(detail))}")
    st, bids2 = c.get("/api/v1/bids")
    row = next((b for b in (bids2 if isinstance(bids2, list) else bids2.get("bids", []))
                if b.get("code") == "2026-api-selftest"), None)
    check("bids 列表行同为超集形状", row is not None and superset_kanban <= _keys(row) and superset_baw <= _keys(row))

    # ── ②b R2/R6：classified 涉密壳（可指定起步 stage + slim profile）与 provenance 来历 ──
    st, rc = c.cmd("bid.create", {"code": "2026-api-shelltest", "client": "别名壳客户",
                                  "kind": "classified", "stage": "S5", "due_at": "2026-10-20 17:00"},
                   key="t-shell-1", agent="api-test")
    check("bid.create classified 壳 + 起步 S5", st == 200 and rc.get("ok") is True, str(rc)[:120])
    st, shell = c.get("/api/v1/bids/2026-api-shelltest")
    check("壳超集形状：kind=classified/stage=S5/slim flow/徽标",
          st == 200 and shell.get("kind") == "classified" and shell.get("stage") == "S5"
          and shell.get("classified") is True and (shell.get("flow", {}).get("nodes") or []) == [],
          f"kind={shell.get('kind')} stage={shell.get('stage')} nodes={len((shell.get('flow') or {}).get('nodes') or [])}")
    st, rr = c.cmd("bid.create", {"code": "2026-api-realstage", "client": "X", "stage": "S5"},
                   key="t-realstage-1", agent="api-test")
    st, realrow = c.get("/api/v1/bids/2026-api-realstage")
    check("real 标忽略 stage 参数强制 S0（门禁不可绕）",
          st == 200 and realrow.get("kind") == "real" and realrow.get("stage") == "S0",
          f"kind={realrow.get('kind')} stage={realrow.get('stage')}")
    st, rb = c.cmd("bid.create", {"code": "2026-api-badkind", "kind": "bogus"}, key="t-badkind-1")
    check("bid.create 非法 kind 报错", "err" in rb, str(rb)[:80])
    st, pv = c.cmd("bid.update_field", {"code": "2026-api-shelltest", "field": "provenance",
                                        "value": "客户直接邀请（微信沟通，无公开公告）", "reason": "壳建档补录"},
                   key="t-prov-1", agent="api-test")
    st, shell2 = c.get("/api/v1/bids/2026-api-shelltest")
    hist = json.loads(shell2.get("lifecycle_history") or "[]") if isinstance(shell2.get("lifecycle_history"), str) else (shell2.get("lifecycle_history") or [])
    check("bid.update_field provenance 写入+留痕",
          st == 200 and pv.get("ok") is True and shell2.get("provenance") == "客户直接邀请（微信沟通，无公开公告）"
          and any(h.get("field") == "provenance" for h in hist), str(pv)[:100])

    # ── ③ 命令网关协议（幂等/审计/agent 署名） ──
    st, r1 = c.cmd("bid.update_field", {"code": "2026-api-selftest", "field": "priority", "value": "P0"},
                   key="t-idem-1", payload_hash="hash-A", agent="agent-x")
    st2, r2 = c.cmd("bid.update_field", {"code": "2026-api-selftest", "field": "priority", "value": "P0"},
                    key="t-idem-1", payload_hash="hash-A")
    check("幂等重放：同 key 同 hash 返回 replay", st == 200 and st2 == 200 and r2.get("replay") is True, str(r2)[:120])
    st3, r3 = c.cmd("bid.update_field", {"code": "2026-api-selftest", "field": "priority", "value": "P1"},
                    key="t-idem-1", payload_hash="hash-B")
    check("幂等冲突：同 key 异 hash 409", st3 == 409, f"st={st3}")
    eid = r1.get("execution_id", "")
    st4, audit = c.get(f"/api/v1/commands/{eid}")
    check("命令审计可查 + X-Agent-Id 落审计",
          st4 == 200 and audit.get("agent_id") == "agent-x" and audit.get("commandId") == "bid.update_field",
          str(audit)[:160])
    st5, r5 = c.cmd("no.such.command", {}, key="t-unknown")
    check("未知命令报错", st5 in (400, 404) and "err" in r5)

    # ── ④ 智能体接触面：登记命令（final 强制降级）+ 工单 + gate 查询 ──
    ws = _TMP / "bids" / "2026-api-selftest" / "data"
    ws.mkdir(parents=True, exist_ok=True)
    art = ws / "stage0.json"
    art.write_text(json.dumps({"lessons_applied": []}, ensure_ascii=False), encoding="utf-8")
    st, r = c.cmd("artifact.register", {"bid_id": "2026-api-selftest", "kind": "draft",
                                        "path": str(art), "status": "final", "producer": "api-test"},
                  agent="agent-w")
    _rr = r.get("result", {})
    check("artifact.register 成功且 final 强制降级为 registered",
          st == 200 and _rr.get("ok") is True and _rr.get("status") == "registered" and _rr.get("fingerprint", "").startswith("sha256:"),
          str(r)[:160])
    st, r = c.cmd("artifact.promote", {"bid_id": "2026-api-selftest", "kind": "draft", "path": str(art)})
    _rp = r.get("result", {})
    check("artifact.promote 指纹未变提升 final", st == 200 and _rp.get("ok") is True and _rp.get("status") == "final", str(r)[:120])
    st, r = c.cmd("run.register", {"agent": "api-test", "bid_id": "2026-api-selftest", "self_check": "pass"})
    _rn = r.get("result", {})
    check("run.register 返回 run_id", st == 200 and _rn.get("ok") is True and _rn.get("run_id", "").startswith("run_"))
    st, r = c.cmd("ticket.generate", {"template": "new-bid-analysis", "bid_id": "2026-api-selftest"})
    check("ticket.generate 成功", st == 200 and r.get("result", {}).get("ok") is True, str(r)[:120])
    st, tl = c.cmd("ticket.list", {}, key="t-ticket-list")
    check("ticket.list 无 NameError（DEV-0042 修复）且返回列表", st == 200 and "err" not in tl, str(tl)[:160])
    st, g = c.get("/api/v1/bids/2026-api-selftest/gate")
    check("gate 阻塞查询 {bid_id, from, to, ok, blockers}",
          st == 200 and {"bid_id", "from", "to", "ok", "blockers"} <= _keys(g), str(g)[:160])
    st, r = c.cmd("bid.advance_stage", {"bid_id": "2026-api-selftest", "to_stage": "S2"})
    check("advance_stage 跳级被门禁拦（ok:false + blockers）",
          st == 200 and r.get("result", r).get("ok") is False and len(r.get("result", r).get("blockers", [])) > 0,
          str(r)[:160])

    # ── ⑤ lead 域：门禁拒绝（save_lead=M3 watcher 同一入口）+ collection.sync 入库 + 关闭区 ──
    from app.services import lead_store as _ls
    ok_bad = _ls.save_lead({"lead_id": "t-bad-lead", "title": "搜索引擎页不是详情页", "buyer": "测试客户B",
                                     "link": "https://www.baidu.com/s?wd=hack", "source": "test",
                                     "published_at": "2026-09-10"})
    check("lead 门禁拒绝：搜索引擎/白名单外 URL 拒入", ok_bad is False)
    good = {
        "lead_id": "t-good-lead", "title": "2026年网络安全服务采购项目测试标讯",
        "buyer": "测试客户C", "link": "https://www.ccgp.gov.cn/cggg/dfgg/gkzb/202609/t20260901_test.htm",
        "source": "test", "published_at": "2026-09-10", "budget": 100, "region": "深圳"}
    ok_good = _ls.save_lead(good)
    st2, leads = c.get("/api/v1/leads?limit=50")
    gl = [l for l in leads.get("leads", []) if l.get("lead_id") == "t-good-lead"]
    lead_shape = {"lead_id", "title", "link", "recommend", "lifecycle", "freshness", "score"}
    check("lead 合规入库 + 列表形状", ok_good is True and len(gl) == 1 and lead_shape <= _keys(gl[0]),
          f"ok={ok_good} keys={sorted(_keys(gl[0])) if gl else 'EMPTY'}")
    st_sync, r_sync = c.cmd("collection.sync", {"items": [dict(good, lead_id="t-sync-lead")]}, key="t-sync-1")
    check("collection.sync 幂等入库", st_sync == 200 and r_sync.get("result", {}).get("applied", 0) == 1, str(r_sync)[:120])
    st_lpv, r_lpv = c.cmd("lead.patch", {"lead_id": "t-good-lead",
                                         "fields": {"provenance": "抓取失败后同事微信转发补录"}},
                          key="t-leadprov-1", agent="api-test")
    check("lead.patch provenance 来历登记", st_lpv == 200 and r_lpv.get("ok") is True
          and "provenance" in ((r_lpv.get("result") or {}).get("patched") or []), str(r_lpv)[:120])
    st_bad, r_bad = c.cmd("lead.patch", {"lead_id": "t-good-lead", "fields": {"provenance_x": "y"}},
                          key="t-leadprov-2")
    check("lead.patch 非白名单字段拒绝", "不支持的字段" in str(r_bad.get("err", "")), str(r_bad)[:100])
    st, closed = c.get("/api/v1/leads/closed?limit=5")
    check("leads/closed 200（列表字段）", st == 200 and "leads" in closed)

    # ── ⑥ 报表/日报/日志 ──
    st, d = c.get("/api/v1/digest")
    check("digest 形状 {ok, date, ...}", st == 200 and d.get("ok") is True and "date" in d, str(_keys(d)))
    st, s = c.get("/api/v1/summary?period=week")
    check("summary 形状（metrics/by_industry/by_region/by_tier/top_clients）",
          st == 200 and {"metrics", "by_industry", "by_region", "by_tier", "top_clients", "period"} <= _keys(s),
          f"keys={sorted(_keys(s))}")
    st, lg = c.get("/api/v1/logs?limit=5")
    check("logs 200", st == 200)

    # ── ⑦ SSE：命令产生事件，流上可见 ──
    sse_ok = _test_sse(port)
    check("SSE /api/v1/stream 收到事件帧", sse_ok)

    # ── ⑧ 废弃端点确实废弃 ──
    st, _ = c.get("/api/v1/flow/template")
    check("独立 flow/template 已废弃（404）", st == 404, f"st={st}")
    st, _ = c.request("PATCH", "/api/v1/bids/2026-api-selftest/priority", {"value": "P1"})
    check("旧 PATCH 直写端点已废弃（404）", st == 404, f"st={st}")

    # 汇总
    failed = [r for r in RESULTS if not r[1]]
    for name, ok_, detail in RESULTS:
        print(("✅" if ok_ else "❌"), name, detail[:80] if not ok_ else "")
    print(f"\nAPI 契约测试：{len(RESULTS) - len(failed)}/{len(RESULTS)} 通过")
    srv.shutdown()
    shutil.rmtree(_TMP, ignore_errors=True)
    return 1 if failed else 0


def _test_sse(port):
    """连 SSE 流 → 触发一条命令 → 5s 内应读到 data: 帧。目标固定常量环回主机。"""
    try:
        s = socket.create_connection((HOST, int(port)), timeout=5)
        s.sendall(b"GET /api/v1/stream HTTP/1.1\r\nHost: 127.0.0.1\r\nAccept: text/event-stream\r\n\r\n")
        conn = http.client.HTTPConnection(HOST, int(port), timeout=5)
        conn.request("POST", "/api/v1/commands",
                     body=json.dumps({"commandId": "bid.add_ai_ready",
                                      "params": {"code": "2026-api-selftest", "item": "SSE 验证项"}}),
                     headers={"Content-Type": "application/json", "Idempotency-Key": "t-sse-1"})
        conn.getresponse().read()
        conn.close()
        s.settimeout(3)
        buf = b""
        deadline = time.time() + 5
        while time.time() < deadline and b"data:" not in buf:
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
        s.close()
        return b"data:" in buf
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
