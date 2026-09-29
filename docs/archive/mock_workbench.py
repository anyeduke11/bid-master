#!/usr/bin/env python3
"""
mock_workbench.py · BidBoard mock 后端 · 端口 8765
用于 S-01/S-02/S-05/S-06 等 Skill 集成测试。
状态: in-memory dict(进程重启数据丢,够 demo 用)

启动:
  python3 mock_workbench.py
  python3 mock_workbench.py --port 9000    # 改端口

API:
  GET    /                          → 健康检查
  GET    /api/bids                   → 列出所有 bids
  POST   /api/bids                   → 创建 bid
  PATCH  /api/bids/<code>/<field>    → 更新字段
  POST   /api/bids/ingest            → 单条写入
  GET    /api/bids/stream            → SSE 模拟(每 30s 推一个心跳)
  GET    /api/stats                  → 统计
  POST   /api/admin/reset            → 重置(bids 清空)
"""
import argparse, json, os, sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# 内存数据
STATE = {
    "bids": [
        # 初始 6 个客户(对照 bid-board-v2-20260810.html 的 demo 数据)
        {"code": "dgyhst2026", "client": "东莞银行", "stage": "修订", "priority": "P0",
         "due_at": "2026-08-13 17:00", "ai_ready": ["JSON 校验", "格式检查"],
         "human_todo": ["报价签字", "述标要点过"], "block": "",
         "last_sync": "2026-08-10 09:30:00", "timeline": [], "flow": {}},
        {"code": "nfh2026", "client": "农发行", "stage": "修订", "priority": "P1",
         "due_at": "2026-08-16 18:00", "ai_ready": ["差异点比对"],
         "human_todo": ["技术方案重写"], "block": "",
         "last_sync": "2026-08-10 09:30:00", "timeline": [], "flow": {}},
        {"code": "unionpay-intl26-1", "client": "银联国际 #1", "stage": "审查", "priority": "P2",
         "due_at": "2026-08-20 17:00", "ai_ready": ["检查表就绪"],
         "human_todo": [], "block": "",
         "last_sync": "2026-08-10 09:30:00", "timeline": [], "flow": {}},
        {"code": "unionpay-intl26-2", "client": "银联国际 #2", "stage": "审查", "priority": "P2",
         "due_at": "2026-08-20 17:00", "ai_ready": ["检查表就绪"],
         "human_todo": [], "block": "分包边界未明",
         "last_sync": "2026-08-10 09:30:00", "timeline": [], "flow": {}},
        {"code": "unionpay-intl26-3", "client": "银联国际 #3", "stage": "审查", "priority": "P2",
         "due_at": "2026-08-20 17:00", "ai_ready": [],
         "human_todo": [], "block": "",
         "last_sync": "2026-08-10 09:30:00", "timeline": [], "flow": {}},
        {"code": "payh26", "client": "平安银行", "stage": "跟踪", "priority": "P2",
         "due_at": "持续", "ai_ready": ["标讯监控中"],
         "human_todo": [], "block": "",
         "last_sync": "2026-08-10 09:30:00", "timeline": [], "flow": {}}
    ]
}

def _find(code):
    return next((b for b in STATE["bids"] if b["code"] == code), None)

def _stats():
    bids = STATE["bids"]
    s = {"total": len(bids), "p0": 0, "p1": 0, "p2": 0, "ready": 0, "blocked": 0, "total_ai": 0}
    for b in bids:
        s[b["priority"].lower()] += 1
        s["total_ai"] += len(b.get("ai_ready", []))
        if b.get("ai_ready"): s["ready"] += 1
        if b.get("block"): s["blocked"] += 1
    s["ready_rate"] = round(s["ready"] / max(s["total"], 1) * 100)
    return s

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # 简化日志
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {self.command} {self.path}  {' '.join(args)}", file=sys.stderr)

    def _send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n: return {}
        raw = self.rfile.read(n)
        try: return json.loads(raw.decode("utf-8"))
        except: return {}

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/" or u.path == "/health":
            return self._send_json(200, {"ok": True, "service": "mock-workbench", "port": 8765, "bids_count": len(STATE["bids"])})
        if u.path == "/api/bids":
            return self._send_json(200, STATE["bids"])
        if u.path == "/api/stats":
            return self._send_json(200, _stats())
        if u.path == "/api/bids/stream":
            # 简化 SSE:发一个 connected 后每 30s 心跳(实际客户端会立即断开,正常)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b"data: {\"type\":\"connected\"}\n\n")
            self.wfile.flush()
            try:
                import time
                while True:
                    time.sleep(30)
                    self.wfile.write(b"data: {\"type\":\"heartbeat\"}\n\n")
                    self.wfile.flush()
            except: pass
            return
        return self._send_json(404, {"err": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        body = self._read_body()
        if u.path == "/api/bids" or u.path == "/api/bids/ingest":
            code = body.get("code", "")
            if not code:
                return self._send_json(400, {"err": "code 必填"})
            existing = _find(code)
            if existing and u.path == "/api/bids":
                return self._send_json(409, {"err": f"code 已存在: {code}"})
            if existing:
                # ingest 模式:更新
                for k, v in body.items():
                    if k != "code":
                        existing[k] = v
                return self._send_json(200, {"ok": True, "mode": "update", "code": code})
            # 创建
            new_bid = {
                "code": code, "client": body.get("client", ""),
                "stage": body.get("stage", "审查"),
                "priority": body.get("priority", "P2"),
                "due_at": body.get("due_at", ""),
                "ai_ready": body.get("ai_ready", []),
                "human_todo": body.get("human_todo", []),
                "block": body.get("block", ""),
                "last_sync": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "timeline": body.get("timeline", []),
                "flow": body.get("flow", {})
            }
            STATE["bids"].append(new_bid)
            return self._send_json(201, {"ok": True, "mode": "create", "code": code, "data": new_bid})
        if u.path == "/api/admin/reset":
            STATE["bids"] = []
            return self._send_json(200, {"ok": True, "msg": "bids cleared"})
        return self._send_json(404, {"err": "not found"})

    def do_PATCH(self):
        u = urlparse(self.path)
        # /api/bids/<code>/<field>
        parts = u.path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "bids":
            code, field = parts[2], parts[3]
            bid = _find(code)
            if not bid:
                return self._send_json(404, {"err": f"客户不存在: {code}"})
            body = self._read_body()
            value = body.get("value")
            # 数组类(ai_ready / human_todo)做去重追加,其他直接覆盖
            if field in ("ai_ready", "human_todo") and isinstance(value, str):
                arr = bid.setdefault(field, [])
                if value not in arr:
                    arr.append(value)
                bid[field] = arr
            else:
                bid[field] = value
            bid["last_sync"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return self._send_json(200, {"ok": True, "code": code, "field": field, "value": bid[field]})
        return self._send_json(404, {"err": "not found"})

    def do_OPTIONS(self):
        # CORS 预检
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"🚀 mock-workbench 启动: http://{args.host}:{args.port}", file=sys.stderr)
    print(f"   初始 bids: {len(STATE['bids'])} 个", file=sys.stderr)
    print(f"   健康检查: curl http://{args.host}:{args.port}/health", file=sys.stderr)
    print(f"   按 Ctrl+C 停止", file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 停止", file=sys.stderr)
        srv.shutdown()

if __name__ == "__main__":
    main()
