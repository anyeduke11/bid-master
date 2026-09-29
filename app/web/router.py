#!/usr/bin/env python3
"""app/web/router.py · 微型路由器（DEV-0042，纯标准库 ~100 行）

模式注册：(method, "/api/v1/bids/{code}") → handler。
handler 签名：handler(req) -> (status_code, payload_dict)
req 为 SimpleNamespace：params（路径参数）、query（parse_qs 结果）、body（JSON）、headers。
"""
import re
from types import SimpleNamespace


class Router:
    def __init__(self):
        self._routes = []  # (method, [segments], handler)

    def add(self, method, pattern, handler):
        segs = [s for s in pattern.strip("/").split("/") if s]
        self._routes.append((method.upper(), segs, handler))

    def get(self, pattern, handler):
        self.add("GET", pattern, handler)

    def post(self, pattern, handler):
        self.add("POST", pattern, handler)

    def patch(self, pattern, handler):
        self.add("PATCH", pattern, handler)

    def resolve(self, method, path):
        """返回 (handler, path_params) 或 None。路径段白名单字符校验防路径注入。"""
        parts = [p for p in path.strip("/").split("/") if p]
        for m, segs, handler in self._routes:
            if m != method.upper() or len(segs) != len(parts):
                continue
            params = {}
            ok = True
            for s, p in zip(segs, parts):
                if s.startswith("{") and s.endswith("}"):
                    name = s[1:-1]
                    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,128}", p):
                        ok = False
                        break
                    params[name] = p
                elif s != p:
                    ok = False
                    break
            if ok:
                return handler, params
        return None


def make_req(params, query, body, headers):
    return SimpleNamespace(params=params, query=query, body=body, headers=headers)
