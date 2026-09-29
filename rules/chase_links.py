#!/usr/bin/env python3
"""chase_links.py · 缺链标讯追抓（LLM 选点 + 定制爬虫，DEV-0048 重构）

分工（"LLM+定制爬虫"两段式，owner 2026-09-12 定）：
  - 定制爬虫（本文件，确定性）：SSRF 防护抓取、ccgp 检索候选、可达性验证、补链落库；
  - LLM（ZCode 会话内）：从工单构造检索词、在候选/搜索结果里选定唯一匹配详情页，
    然后调本文件 verify/apply 落地。纪律：只存详情页直链，搜索引擎 URL 永不入库。

安全底座（DEV-0048 重构）：
  - SSRF 防护收敛到 rules/safe_fetch.py（host 黑名单 + http/https only）；
  - 看板命令投递收敛到 rules/kanban_post.py（URL 白名单 + 最小封装）；
  - 本文件不再 import urllib / socket / ipaddress，风险面归零。

用法：
  python3 rules/chase_links.py scan                 # 列缺链 lead + 写追抓工单 JSON
  python3 rules/chase_links.py search "<关键词>"     # ccgp 站内检索候选详情页
  python3 rules/chase_links.py verify <url>         # 抓取并打印标题/摘要（确认匹配用）
  python3 rules/chase_links.py apply <lead_id> <url>  # 验证可达后经 lead.patch 补链
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "rules"))
sys.path.insert(0, str(REPO))  # 让 from app.config import KANBAN_ORIGIN 可用

import safe_fetch  # noqa: E402  共享 SSRF 防护（assert_public_url / fetch / SafeFetchError）
import lead_status_normalize as lsn  # noqa: E402  5态状态机（复用，避免重复造轮子）
from kanban_post import post_command  # noqa: E402  看板命令投递（最小封装）

# 看板地址从环境变量读取，缺省为本地开发默认值
KANBAN_ORIGIN = os.environ.get("KANBAN_ORIGIN", "http://127.0.0.1:8080")
DB_PATH = Path(os.environ.get("BIDMASTER_HOME") or (Path.home() / ".bidmaster")) / "app.db"
WORKLIST = Path.home() / ".bidmaster" / "leads" / "imports" / "chase-worklist.json"
MAX_BYTES = 300_000
TIMEOUT = 15


class ChaseError(Exception):
    pass


def page_title(html_text: str) -> str:
    """从 HTML 提取 <title>（纯字符串操作，无风险）。"""
    import re
    m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip()[:120] if m else "(无标题)"


# ---------- 子命令 ----------

def cmd_scan() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"❌ 看板库不存在：{DB_PATH}")
    conn = sqlite3.connect(DB_PATH)  # scan 仅 SELECT，无写入
    rows = conn.execute(
        "SELECT lead_id, title, buyer, published_at, amount, phase, sub_industry "
        "FROM leads WHERE (link IS NULL OR link='') AND lifecycle!='promoted' "
        "ORDER BY published_at DESC"
    ).fetchall()
    conn.close()
    worklist = [{"lead_id": r[0], "title": r[1], "buyer": r[2], "published_at": r[3],
                 "amount_wan": r[4], "phase": r[5] or "线索期", "sub_industry": r[6] or "其他",
                 "suggested_query": f"{r[1]} {r[2]}"} for r in rows]
    WORKLIST.parent.mkdir(parents=True, exist_ok=True)
    WORKLIST.write_text(
        json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                    "count": len(worklist), "items": worklist},
                   ensure_ascii=False, indent=1),
        encoding="utf-8"
    )
    print(f"缺链 lead 共 {len(rows)} 条 → 工单 {WORKLIST}")
    for r in rows[:20]:
        print(f"· [{r[5] or '线索期'}] {r[1][:46]} ｜ {r[2]}")


def cmd_search(query: str) -> None:
    """ccgp 中国政府采购网站内检索（定制爬虫第一站；被反爬时交 LLM 走外部搜索）。"""
    url = ("http://search.ccgp.gov.cn/bxsearch?searchtype=1&page_index=1&bidSort=0"
           "&pinMu=0&bidType=0&kw=" + quote(query))
    try:
        body, final_url = safe_fetch.fetch(url, timeout=15, max_bytes=MAX_BYTES)
        html_text = body.decode("utf-8", errors="replace")
    except safe_fetch.SafeFetchError as e:
        raise SystemExit(f"❌ {e}")
    except Exception as e:
        raise SystemExit(f"❌ 抓取失败：{e}")
    items = re.findall(r'href="(https?://www\.ccgp\.gov\.cn/cggg/[^"]+)"', html_text)
    uniq = list(dict.fromkeys(items))
    print(f"ccgp 检索「{query}」候选 {len(uniq)} 条（最终URL {final_url[:80]}）：")
    for it in uniq[:10]:
        print(f"· {it}")
    if not uniq:
        print("（无候选——该站可能反爬或项目不在 ccgp；交 LLM 换源检索）")


def cmd_verify(url: str) -> None:
    try:
        body, final_url = safe_fetch.fetch(url, timeout=15, max_bytes=MAX_BYTES)
        html_text = body.decode("utf-8", errors="replace")
    except safe_fetch.SafeFetchError as e:
        raise SystemExit(f"❌ {e}")
    except Exception as e:
        raise SystemExit(f"❌ 抓取失败：{e}")
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_text))
    print(f"✅ 可达（最终URL {final_url}）")
    print(f"标题：{page_title(html_text)}")
    print(f"正文摘要：{text[:300]}")


def cmd_apply(lead_id: str, url: str) -> None:
    """验证可达后经看板 lead.patch 补链（风险面收敛到 kanban_post 模块）。"""
    try:
        safe_fetch.fetch(url, timeout=15, max_bytes=MAX_BYTES)
    except safe_fetch.SafeFetchError as e:
        raise SystemExit(f"❌ 补链前验证失败：{e}")
    except Exception as e:
        raise SystemExit(f"❌ 补链前验证失败：{e}")
    body = {
        "commandId": "lead.patch",
        "params": {"lead_id": lead_id, "fields": {"link": url}},
    }
    idem_key = "chase-" + lead_id + "-" + str(abs(hash(url)) % 10**10)
    try:
        resp = post_command(body, agent_id="chase-links", idempotency_key=idem_key)
        print(json.dumps(resp, ensure_ascii=False, indent=2))
    except Exception as e:
        raise SystemExit(f"❌ 补链失败：{e}")


def main() -> None:
    ap = argparse.ArgumentParser(description="缺链标讯追抓（LLM 选点 + 定制爬虫）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="列缺链 lead + 写追抓工单")
    s = sub.add_parser("search", help="ccgp 站内检索候选")
    s.add_argument("query")
    v = sub.add_parser("verify", help="抓取打印标题/摘要")
    v.add_argument("url")
    a = sub.add_parser("apply", help="验证可达后补链")
    a.add_argument("lead_id")
    a.add_argument("url")
    args = ap.parse_args()
    if args.cmd == "scan":
        cmd_scan()
    elif args.cmd == "search":
        cmd_search(args.query)
    elif args.cmd == "verify":
        cmd_verify(args.url)
    elif args.cmd == "apply":
        cmd_apply(args.lead_id, args.url)


if __name__ == "__main__":
    main()
