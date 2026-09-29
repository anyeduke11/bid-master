#!/usr/bin/env python3
"""kanban_post.py · 本机看板命令投递（最小封装）

职责：把命令/查询投递到本地看板 API，做 URL 白名单校验。
风险面：本文件只访问本机看板（127.0.0.1:8080 白名单），不做通用 HTTP 抓取。

DEV-0059 扩展：get_json / post_json 通用化（MCP server 与 bid CLI 复用同一白名单原语），
post_command 保持原签名兼容既有调用方（chase_links 等）。
"""

import json
import os
import urllib.request
from urllib.parse import urlparse

# 从环境变量读取，缺省为本地看板默认端口；避免在规则文件硬编码环回地址
KANBAN_ORIGIN = os.environ.get("KANBAN_ORIGIN", "http://127.0.0.1:8080")
KANBAN_HOSTS = {"127.0.0.1:8080"}


def _validate() -> str:
    """白名单校验：仅 http(s) + 本机白名单 host:port。通过则返回规范化 origin。"""
    u = urlparse(KANBAN_ORIGIN)
    if u.scheme not in ("http", "https"):
        raise ValueError(f"协议拒绝：{u.scheme}")
    hostport = f"{u.hostname}:{u.port}" if u.port else (u.hostname or "")
    if hostport not in KANBAN_HOSTS:
        raise ValueError(f"目标不在白名单：{hostport}")
    return KANBAN_ORIGIN


def _request(method: str, path: str, body: dict | None, agent_id: str,
             idempotency_key: str = "", timeout: int = 30) -> dict:
    origin = _validate()
    if not str(path).startswith("/api/v1/"):
        raise ValueError(f"非法 API 路径：{path}")
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json", "X-Agent-Id": agent_id}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    req = urllib.request.Request(origin + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_command(body: dict, agent_id: str = "chase-links",
                 idempotency_key: str = "") -> dict:
    """POST /api/v1/commands 到本地看板，返回 JSON（既有签名，兼容旧调用方）。"""
    return _request("POST", "/api/v1/commands", body, agent_id, idempotency_key)


def post_json(path: str, body: dict | None = None, agent_id: str = "mcp",
              timeout: int = 30) -> dict:
    """POST 任意 /api/v1/ 路径（如 /api/v1/capture/run）。"""
    return _request("POST", path, body, agent_id, timeout=timeout)


def get_json(path: str, agent_id: str = "mcp", timeout: int = 30) -> dict:
    """GET 任意 /api/v1/ 路径（health/digest/leads 等只读查询）。"""
    return _request("GET", path, None, agent_id, timeout=timeout)
