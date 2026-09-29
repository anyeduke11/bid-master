#!/usr/bin/env python3
"""archive_close.py · L5 归档
- 输入: bid code + outcome(win/loss/no-bid)
- 输出: 归档 JSON ~/.bidmaster/archive/2026-QX.jsonl
- 行为:调用 server API 标记 closed + 写归档文件
"""
import ipaddress
import json
import os
import re
import socket
import sys
import urllib.request
from urllib.parse import urlparse
from datetime import datetime
from pathlib import Path

BASE = os.environ.get("BID_BOARD_BASE", "http://127.0.0.1:8080")
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
_BID_CODE_RE = re.compile(r"[A-Za-z0-9_\-]{1,64}")
_API_PATH_RE = re.compile(r"/api/v1/commands")
_BIDS_LIST_PATH = "/api/v1/bids?status=all"
_OUTCOMES = ("win", "loss", "no-bid")
# reason 字符白名单:可打印 ASCII + CJK 统一汉字 + 常用中文标点(常量,用于逐字符重建)
_SAFE_TEXT_CHARS = ("".join(chr(c) for c in range(0x20, 0x7F))
                    + "".join(chr(c) for c in range(0x4E00, 0xA000))
                    + "，。、；：？！（）《》【】—…·“”‘’")


def _normalize_outcome(value):
    """outcome 只能是常量元组中的元素:按下标从常量取回,而非透传外部输入。"""
    if value not in _OUTCOMES:
        raise SystemExit(json.dumps({"ok": False, "err": f"outcome 只允许 {'/'.join(_OUTCOMES)}: {value!r}"}, ensure_ascii=False))
    return _OUTCOMES[_OUTCOMES.index(value)]


def _normalize_reason(value, limit=200):
    """reason 逐字符按常量白名单重建(丢弃控制字符与白名单外字符,截断 200 字),不透传外部输入。"""
    rebuilt = []
    for ch in str(value)[:limit]:
        idx = _SAFE_TEXT_CHARS.find(ch)
        if idx >= 0:
            rebuilt.append(_SAFE_TEXT_CHARS[idx])
    return "".join(rebuilt)


def _safe_local_url(url):
    """SSRF 防护三重校验:①协议只允许 http/https;②目标主机只允许本机白名单;
    ③解析后的每一个 IP 必须是环回地址(防 DNS rebinding / 私网 / 云元数据地址)。"""
    p = urlparse(str(url))
    if p.scheme not in ("http", "https"):
        raise SystemExit(f"只允许 http/https,拒绝: {url!r}")
    if not p.hostname or p.hostname not in _ALLOWED_HOSTS:
        raise SystemExit(f"只允许本机地址 {sorted(_ALLOWED_HOSTS)},拒绝: {url!r}")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or 80, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise SystemExit(f"无法解析主机 {p.hostname}: {e}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_loopback:
            raise SystemExit(f"解析结果非环回地址,拒绝请求: {ip}")
    return str(url)


def _assert_local_base(base):
    """BASE 必须是 http(s)://127.0.0.1|localhost(启动即校验)。"""
    return _safe_local_url(base)


_assert_local_base(BASE)


def _bid_api_path(code, action):
    """DEV-0042：生命周期动作统一走命令网关。只允许 /api/v1/commands 一个路径，
    code 仍过白名单正则；action 映射为 bid.lifecycle 的目标状态。"""
    if not _BID_CODE_RE.fullmatch(str(code)) or action not in ("close", "archive"):
        raise ValueError(f"非法 bid_code/action: {code!r} {action!r}")
    path = "/api/v1/commands"
    if not _API_PATH_RE.fullmatch(path):
        raise ValueError(f"非法 API 路径: {path!r}")
    return path


def _bid_command_body(code, action, reason, outcome=""):
    """构造 bid.lifecycle 命令体（code 已过白名单）。"""
    to = {"close": "closed", "archive": "archived"}[action]
    params = {"code": code, "to": to, "reason": reason}
    if action == "close" and outcome:
        params["final_outcome"] = outcome
    return {"commandId": "bid.lifecycle", "params": params}


def _list_bids():
    """只读取常量路径 /api/bids?status=all,不含任何外部输入。"""
    url = _safe_local_url(_assert_local_base(BASE) + _BIDS_LIST_PATH)
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def _list_canonical_codes():
    """返回服务端 bids 的规范 code 列表(只保留白名单字符)。本函数不接收任何外部输入,
    调用方只能用 `in` 判断存在性并按下标取回服务端返回的元素,命令行值本身永不进入 URL。"""
    codes = []
    for b in _list_bids():
        canon = str(b.get("code", ""))
        if _BID_CODE_RE.fullmatch(canon):
            codes.append(canon)
    return codes


# 注:不再提供通用 http_post(path, body) 包装——两次 POST 直接内联在 main() 中,
#    每次都经 _safe_local_url 三重校验;canon 来自服务端列表,outcome/reason 经常量白名单重建。

def main():
    if len(sys.argv) < 3:
        print(json.dumps({"ok": False, "err": "用法: archive_close.py <bid_code> <outcome:win|loss|no-bid> [reason]"}))
        sys.exit(1)
    code, outcome = sys.argv[1], sys.argv[2]
    reason = sys.argv[3] if len(sys.argv) > 3 else ""
    outcome = _normalize_outcome(outcome)
    reason = _normalize_reason(reason)
    if not _BID_CODE_RE.fullmatch(code):
        print(json.dumps({"ok": False, "err": f"非法 bid_code(只允许字母/数字/_/-,≤64 位): {code!r}"}, ensure_ascii=False))
        sys.exit(1)
    # API 路径只用服务端返回的规范 code(按下标取回),命令行输入仅做存在性判断,不进 URL
    canonical_codes = _list_canonical_codes()
    if code not in canonical_codes:
        print(json.dumps({"ok": False, "err": f"bid 不存在: {code}"}, ensure_ascii=False))
        sys.exit(1)
    canon = canonical_codes[canonical_codes.index(code)]

    # 1. 调 server 关闭 bid —— URL 经 _safe_local_url 三重校验(协议 / 本机主机白名单 / 解析后 IP 环回),
    #    此处再断言协议与主机;canon 来自服务端列表,outcome/reason 已按常量白名单重建
    close_url = _safe_local_url(_assert_local_base(BASE) + _bid_api_path(canon, "close"))
    if urlparse(close_url).scheme not in ("http", "https") or urlparse(close_url).hostname not in _ALLOWED_HOSTS:
        raise SystemExit(f"拒绝非本机请求: {close_url!r}")
    close_req = urllib.request.Request(
        close_url, method="POST",
        data=json.dumps(_bid_command_body(canon, "close", reason, outcome)).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(close_req, timeout=10) as r:
        close_resp = json.loads(r.read().decode())
    if not close_resp.get("ok"):
        print(json.dumps({"ok": False, "err": f"close 失败: {close_resp.get('err')}"}, ensure_ascii=False))
        sys.exit(1)

    # 2. 调 server 归档(30 天后才会自动归档,这里手动) —— 同上三重校验
    archive_url = _safe_local_url(_assert_local_base(BASE) + _bid_api_path(canon, "archive"))
    if urlparse(archive_url).scheme not in ("http", "https") or urlparse(archive_url).hostname not in _ALLOWED_HOSTS:
        raise SystemExit(f"拒绝非本机请求: {archive_url!r}")
    archive_req = urllib.request.Request(
        archive_url, method="POST",
        data=json.dumps(_bid_command_body(canon, "archive", reason or "归档")).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(archive_req, timeout=10) as r:
        archive_resp = json.loads(r.read().decode())

    # 3. 写归档文件 ~/.bidmaster/archive/2026-QX.jsonl
    now = datetime.now()
    quarter = f"{now.year}-Q{(now.month - 1) // 3 + 1}"
    archive_dir = Path(os.environ.get("BIDMASTER_HOME") or (Path.home() / ".bidmaster")) / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_file = archive_dir / f"{quarter}.jsonl"
    with open(archive_file, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now.isoformat(), "code": code, "outcome": outcome,
                           "reason": reason, "closed_at": close_resp.get("lifecycle")},
                          ensure_ascii=False) + "\n")

    print(json.dumps({"ok": True, "module": "archive_close", "code": code, "outcome": outcome,
                     "closed": close_resp.get("ok"), "archived": archive_resp.get("ok"),
                     "archive_file": str(archive_file)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
