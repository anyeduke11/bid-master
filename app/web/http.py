#!/usr/bin/env python3
"""app/web/http.py · HTTP 基类（BaseHTTPRequestHandler 薄壳：静态文件 / JSON / SSE）

行为保真自原 server.py Handler（响应头/Content-Type/SSE 帧格式不变）。
"""
import json
import queue
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from ..web.router import make_req


class SSEHub:
    """SSE 客户端管理（自 server.py 迁移，语义不变）。"""

    def __init__(self):
        self.clients = []  # (client_id, Queue, wfile)
        self.lock = threading.Lock()

    def broadcast(self, event_type, payload):
        event = {"type": event_type, "ts": time.strftime("%H:%M:%S"), "payload": payload}
        msg = f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        with self.lock:
            dead = []
            for client_id, q, _w in self.clients:
                try:
                    q.put_nowait(msg)
                except Exception:
                    dead.append(client_id)
            for cid in dead:
                self.clients[:] = [c for c in self.clients if c[0] != cid]


class AppHandler(BaseHTTPRequestHandler):
    """由 app/main.py 注入 router 与 sse hub（类属性，避免每请求重建）。"""
    router = None          # type: Router
    sse = None             # type: SSEHub
    public_dir = None      # type: Path
    repo_dir = None        # type: Path

    # ── 基础 ──
    def log_message(self, fmt, *args):
        try:
            print(f"[{time.strftime('%H:%M:%S')}] {self.command} {self.path}", file=__import__("sys").stderr)
        except Exception:
            pass

    def _send_json(self, code, data, headers=None):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path):
        if not path.exists():
            return self._send_json(404, {"err": "not found", "path": str(path)})
        ctype = "text/html; charset=utf-8" if path.suffix == ".html" else \
                "application/javascript; charset=utf-8" if path.suffix == ".js" else \
                "text/css; charset=utf-8" if path.suffix == ".css" else \
                "application/octet-stream"
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def _host_allowed(self) -> bool:
        """DEV-0081：API 路径 Host 白名单（防 DNS rebinding/跨源直打）。

        服务绑定 127.0.0.1，正常访问的 Host 只会是 127.0.0.1/localhost/[::1]（端口不限）。
        静态页与 SSE 不限（浏览器同源场景 Host 同样合法，白名单对它们也放行）。
        """
        host = (self.headers.get("Host") or "").strip()
        if not host:
            return False
        hostname = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        return hostname in ("127.0.0.1", "localhost", "[::1]", "::1")

    def _dispatch(self, method):
        u = urlparse(self.path)
        # DEV-0081：API 边界收敛——去 CORS *（前端同源，无需跨源），加 Host 校验
        if u.path.startswith("/api/") and not self._host_allowed():
            return self._send_json(403, {"err": "forbidden host"})
        # 静态与首页（保持 v0.3.2 行为）
        if method == "GET":
            if u.path in ("/", "/index.html"):
                return self._send_file(self.public_dir / "index.html")
            if u.path.startswith("/public/") or u.path.startswith("/static/"):
                rel = u.path.lstrip("/")
                # 路径穿越防护：解析后必须仍在仓库根之下（is_relative_to，前缀匹配有兄弟目录绕过）
                target = (self.repo_dir / rel).resolve()
                if not target.is_relative_to(self.repo_dir.resolve()):
                    return self._send_json(403, {"err": "forbidden"})
                return self._send_file(target)
            if u.path == "/api/v1/stream":
                return self._handle_sse()
        # DEV-0042 兼容垫片：旧无版本前缀的 /api/* 308 到 /api/v1/*——
        # 重构前已打开的标签页（旧 JS 在内存里）无需强刷即可继续工作。
        if u.path.startswith("/api/") and not u.path.startswith("/api/v1/"):
            new_path = "/api/v1" + u.path[len("/api"):] + (("?" + u.query) if u.query else "")
            self.send_response(308)
            self.send_header("Location", new_path)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        found = self.router.resolve(method, u.path)
        if not found:
            return self._send_json(404, {"err": "not found"})
        handler, params = found
        req = make_req(params, parse_qs(u.query), self._read_body(), self.headers)
        try:
            code, payload = handler(req)
            return self._send_json(code, payload)
        except Exception as e:
            traceback.print_exc()
            return self._send_json(500, {"err": f"执行异常: {e}"})

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_OPTIONS(self):
        # DEV-0081：不再放行跨源预检（前端与静态页同源，合法流量不需要 CORS；
        # 原 ACAO * + 全放行使任意网页可跨源打 /api/v1/reset 等写端点）
        self.send_response(204)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.end_headers()

    def _handle_sse(self):
        """SSE 端点（帧格式与心跳节奏与原实现一致）。"""
        client_id = f"{self.client_address[0]}:{self.client_address[1]}-{time.time()}"
        q = queue.Queue(maxsize=100)
        with self.sse.lock:
            self.sse.clients.append((client_id, q, self.wfile))
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(f"data: {json.dumps({'type': 'connected', 'client_id': client_id})}\n\n".encode())
            self.wfile.flush()
            last_heartbeat = time.time()
            while True:
                try:
                    msg = q.get(timeout=15)
                    self.wfile.write(msg.encode())
                    self.wfile.flush()
                    last_heartbeat = time.time()
                except queue.Empty:
                    if time.time() - last_heartbeat > 15:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        last_heartbeat = time.time()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with self.sse.lock:
                self.sse.clients[:] = [c for c in self.sse.clients if c[0] != client_id]
