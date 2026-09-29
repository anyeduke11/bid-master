#!/usr/bin/env python3
"""safe_fetch.py · 受约束 HTTP 取数器（Mimosa + WS-2026-09-13 L2）

约束（来自 Mimosa hook 与 AGENTS.md L3 红线）：
  - 仅允许 http/https 协议；其余 scheme 一律拒。
  - 请求前 resolve host → 解析全部 IP；任一 IP 落在下列范围即拒：
    loopback / private / link-local / multicast / reserved / unspecified。
  - 重定向前复验目标 URL（同样约束）。
  - 跟随重定向上限 5 次；同源/跨源都不放松以上约束。

用法：
  from rules.safe_fetch import fetch, SafeFetchError, UA
  text, final_url = fetch(url, timeout=15, max_bytes=300_000)

CLI 自检：
  python3 rules/safe_fetch.py selftest
"""

import ipaddress
import socket
import sys
from urllib.parse import urlparse

try:
    import urllib.request
except ImportError:  # pragma: no cover
    urllib = None  # type: ignore


UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


class SafeFetchError(Exception):
    """受约束 fetch 失败：协议拒绝 / host 黑名单 / 超长 / 重定向逃逸等。"""


# ---------- IP 黑名单 ----------

def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    """返回 True 即视为不可外访（环回/私有/链路本地/组播/保留/未指定）。"""
    if isinstance(ip, ipaddress.IPv4Address):
        return bool(
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    # IPv6
    return bool(
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def assert_public_url(url: str) -> str:
    """仅 http/https；解析 host 全部 IP，命中黑名单即抛 SafeFetchError。"""
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise SafeFetchError(f"协议拒绝：{u.scheme!r}（仅 http/https）")
    host = u.hostname
    if not host:
        raise SafeFetchError("URL 缺 host")
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as e:
        raise SafeFetchError(f"host 解析失败：{host}（{e}）")
    ips = []
    for info in infos:
        try:
            ips.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    if not ips:
        raise SafeFetchError(f"host 无可解析 IP：{host}")
    for ip in ips:
        if _is_blocked_ip(ip):
            raise SafeFetchError(f"host 黑名单命中：{host} → {ip}")
    return u.geturl()


# ---------- fetch 主流程 ----------

DEFAULT_TIMEOUT = 15
DEFAULT_MAX_BYTES = 300_000
DEFAULT_MAX_REDIRECT = 5


def fetch(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_redirect: int = DEFAULT_MAX_REDIRECT,
    headers: dict | None = None,
) -> tuple[bytes, str]:
    """取回受约束 HTTP 内容；返回 (bytes, final_url)。

    - 解析前调 assert_public_url 拦截 SSRF。
    - 跟随重定向前对每个 Location 重做 assert_public_url。
    - 单响应体超过 max_bytes 抛 SafeFetchError（防 OOM/防滥用为大文件下载）。
    """
    if urllib is None:  # pragma: no cover
        raise SafeFetchError("当前环境无 urllib.request")

    current = assert_public_url(url)
    req_headers = dict(UA)
    if headers:
        req_headers.update(headers)

    last_err = None
    for hop in range(max_redirect + 1):
        req = urllib.request.Request(current, headers=req_headers)
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except Exception as e:
            raise SafeFetchError(f"fetch 失败 [{current}]：{e}") from e
        status = getattr(resp, "status", None) or resp.getcode()
        # 重定向
        if status in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            resp.close()
            if not location:
                raise SafeFetchError(f"重定向无 Location [{current}]")
            # urljoin 由 urllib 自动做（Request 接受相对），但仍走 URL 解析
            from urllib.parse import urljoin
            nxt = urljoin(current, location)
            current = assert_public_url(nxt)  # 关键：每跳都重新校验
            continue
        # 正常响应
        body = resp.read(max_bytes + 1)
        resp.close()
        if len(body) > max_bytes:
            raise SafeFetchError(f"响应体超 {max_bytes} 字节 [{(len(body)-1)}B · {current}]")
        return body, current

    raise SafeFetchError(f"重定向次数超限（>{max_redirect}）from {url}")


# ---------- CLI 自检 ----------

def _selftest():
    cases = [
        ("http://127.0.0.1/", True, "环回拒"),
        ("http://localhost/", True, "环回（解析到 127）拒"),
        ("http://10.0.0.1/", True, "RFC1918 拒"),
        ("http://192.168.1.1/", True, "RFC1918 拒"),
        ("file:///etc/passwd", True, "file scheme 拒"),
        ("ftp://example.com/", True, "ftp scheme 拒"),
        ("javascript:alert(1)", True, "javascript scheme 拒"),
        ("https://www.baidu.com/", False, "公网 https 过"),
        ("https://www.gov.cn/", False, "公网 https 过"),
    ]
    fails = 0
    for url, should_reject, label in cases:
        try:
            assert_public_url(url)
            rejected = False
        except SafeFetchError:
            rejected = True
        ok = (rejected == should_reject)
        flag = "✓" if ok else "✗"
        if not ok:
            fails += 1
        print(f"{flag} {label:18s} {url:38s} → rejected={rejected} expect={should_reject}")
    print()
    if fails:
        print(f"❌ selftest 失败 {fails}/{len(cases)}")
        sys.exit(1)
    print(f"✅ selftest 通过 {len(cases)}/{len(cases)}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        _selftest()
    else:
        print(__doc__)
        sys.exit(2)