#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lead_capture_crawl4ai.py · L1 标讯真抓取脚本(crawl4ai + playwright)
================================================================
v0.4.1 链路诚实化（DEV-0052）:实测 CEB 列表页 href 全为主页占位符
  （urlOpen('http://www.cebpubservice.com/')，渲染后亦不变，站点设计即如此），
  假锚点链接不再写入 link 字段（误导下游 lead-status-check / 人工点击）：
  - link 字段：仅存经 ccgp 标题检索找回并验证的真实详情直链，否则留空；
  - 列表页锚点仅作 lead_id 去重身份键（内部稳定，不外露）；
  - 补链走 safe_fetch SSRF 防护 + 标题相似度 ≥0.5 双重门槛，失败即留空不硬凑。

抓取策略:
  1. 抓 cebpubservice.com 公告列表(招标公告 / 中标结果 / 中标候选人)
  2. 用 crawl4ai 浏览器渲染页面，提取 bid 条目
  3. ccgp 站内检索按标题找回真实详情页 URL（找回失败 link 留空）
  4. crawl4ai 访问详情页，提取结构化字段
  5. 过滤过期/终止标讯，写入 leads.jsonl

与旧版 lead_capture.py 的兼容性:
  - 输出 schema 不变（link 可为空串）；
  - CLI 接口一致 (--date, --self-test 等)；
  - 去重/时效/SSRF 逻辑一致。
"""
import asyncio
import difflib
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, date
from pathlib import Path
from urllib.parse import quote, urlparse

# 复用 rules/safe_fetch.py 的 SSRF 防护（缺 rules/ 时降级为不补链，不影响主流程）
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "rules"))
try:
    import safe_fetch  # noqa: E402
except ImportError:  # pragma: no cover
    safe_fetch = None

try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
except ImportError:
    print("❌ crawl4ai 未安装，请先运行: pip install crawl4ai playwright && playwright install chromium")
    sys.exit(1)

# BAW v0.4.0（W4 4.1 移植）：抓取结果改写数据面 ~/.bidmaster/leads/，经 bid-scout 打分 + validate_leads 转正
OUT = Path.home() / ".bidmaster" / "leads" / "raw" / "leads.jsonl"
SEEN = Path.home() / ".bidmaster" / "leads" / "leads.seen"

# SSRF 防护: 只抓取公网 http/https 地址
def _is_public_http_url(url):
    try:
        p = urlparse(str(url))
    except Exception:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    host = p.hostname.lower().strip("[]")
    if host in ("localhost", "0.0.0.0") or host.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        import ipaddress
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified)

# 网安/数据安全类关键字(Duke 关心的)
SEC_KW = ("安全", "网络", "数据", "等级保护", "等保", "密码", "态势",
          "防火墙", "防护", "审计", "监测", "渗透", "应急", "加固",
          "VPN", "零信任", "SDP", "SOC", "SIEM", "EDR", "XDR", "日志",
          "测评", "密评", "风险评估", "应急演练", "备份", "容灾")

# Duke 严令"过期的标讯禁止入库"——这里"过期"指 published 太久,对营销无帮助
_default_fresh = "90" if os.environ.get("BID_BOARD_DEMO_MODE", "0") == "1" else "45"
FRESH_DAYS = int(os.environ.get("BID_BOARD_FRESH_DAYS", _default_fresh))

# 终止/已结束标讯关键词
TERMINATED_KW = ("中标结果", "已中标", "候选人公示", "废标", "终止", "变更",
                 "结果公示", "流标", "暂停", "取消")

# 抓取源 (仅 cebpubservice，与旧版一致)
LIST_URLS = [
    "https://bulletin.cebpubservice.com/biddingBulletin/index.html",
    "https://bulletin.cebpubservice.com/resultBulletin/index.html",
    "https://bulletin.cebpubservice.com/candidateBulletin/index.html",
]

# 行业/区域映射 (与旧版一致)
INDUSTRY_KW_ORDERED = [
    ("银行", "银行"), ("股份", "银行"), ("信用社", "金融"), ("信用合作", "金融"),
    ("证券", "证券"), ("保险", "金融"), ("基金", "金融"), ("期货", "金融"),
    ("资产管理", "金融"),
    ("医院", "医疗"), ("卫生院", "医疗"), ("卫生服务", "医疗"),
    ("医保", "医疗"), ("医疗保障", "医疗"), ("康复", "医疗"),
    ("疾控", "医疗"), ("卫生健康", "医疗"), ("卫健委", "医疗"),
    ("大学", "教育"), ("学院", "教育"), ("学校", "教育"),
    ("中学", "教育"), ("小学", "教育"), ("教育局", "教育"), ("教育厅", "教育"),
    ("电力", "能源"), ("电网", "能源"), ("电厂", "能源"),
    ("供电", "能源"), ("石化", "能源"), ("石油", "能源"), ("天然气", "能源"),
    ("电信", "电信"), ("通信", "电信"), ("移动", "电信"), ("联通", "电信"),
    ("铁塔", "电信"),
    ("政府", "政府"), ("监管", "政府"), ("管理局", "政府"),
    ("委员会", "政府"), ("办公厅", "政府"), ("办公室", "政府"),
    ("政务", "政府"), ("行政", "政府"), ("机关", "政府"),
    ("研究院", "政府"), ("研究所", "政府"),
]

BUYER_PREFIXES = (
    "中国电信", "中国移动", "中国联通", "中国广电", "中国铁塔",
    "中国银行", "中国建设银行", "中国工商银行", "中国农业银行", "交通银行", "招商银行", "中信银行",
    "国家电网", "南方电网", "中国石油", "中国石化", "中海油",
    "中国邮政", "国家税务总局", "海关总署", "公安部", "教育部",
)


def is_fresh(published_at):
    """检查 published_at 距今是否 ≤ FRESH_DAYS 天。"""
    if not published_at:
        return True
    try:
        pub_date = datetime.strptime(published_at[:10], "%Y-%m-%d").date()
        days = (date.today() - pub_date).days
        return 0 <= days <= FRESH_DAYS
    except Exception:
        return True


def is_terminated(title):
    """检查标题是否含终止/已结束关键词。"""
    t = title or ""
    return any(kw in t for kw in TERMINATED_KW)


def guess_buyer_from_title(title):
    """从 title 提取可能的采购人。"""
    pat = re.compile(r'([\u4e00-\u9fa5]{2,12}(?:公司|集团|分行|支行|局|院|校|医院|银行|事务所|中心|学校|大学|学院|委员会|办公室|办公厅))')
    m = pat.search(title or "")
    return m.group(1) if m else "未披露"


def infer_industry_region(title):
    """从 title 推断行业和区域。"""
    blob = title or ""
    ind, reg = "通用", "全国"
    for kw, industry in INDUSTRY_KW_ORDERED:
        if kw in blob:
            ind = industry
            break
    for city, region in {
        "北京": "华北", "天津": "华北", "河北": "华北", "山西": "华北", "内蒙古": "华北",
        "上海": "华东", "江苏": "华东", "浙江": "华东", "安徽": "华东",
        "福建": "华东", "江西": "华东", "山东": "华东",
        "广东": "华南", "广西": "华南", "海南": "华南",
        "湖北": "华中", "湖南": "华中", "河南": "华中",
        "辽宁": "东北", "吉林": "东北", "黑龙江": "东北",
        "四川": "西南", "重庆": "西南", "贵州": "西南", "云南": "西南", "西藏": "西南",
        "陕西": "西北", "甘肃": "西北", "青海": "西北", "宁夏": "西北", "新疆": "西北",
    }.items():
        if city in blob:
            reg = region
            break
    return ind, reg


def load_seen():
    if not SEEN.exists():
        return set()
    return set(SEEN.read_text(encoding="utf-8").splitlines())


def save_seen(seen):
    SEEN.parent.mkdir(parents=True, exist_ok=True)
    SEEN.write_text("\n".join(sorted(seen)) + "\n", encoding="utf-8")


def _clean_title_for_query(title):
    """标题清洗为 ccgp 检索词：去【】区域标记与书名号，截断 30 字。"""
    t = re.sub(r"【[^】]*】", "", title or "")
    t = re.sub(r"[《》「」『』()（）]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:30]


# ccgp 反爬熔断（进程级）：一旦命中"频繁访问"拦截页，本次运行不再重试
_ccgp_blocked = False


def recover_link_via_ccgp(title):
    """按标题在 ccgp 站内检索找回真实详情直链。

    双重门槛防错链：候选详情页可达 + <title> 与抓取标题相似度 ≥ 0.5。
    任一环节失败/不确定 → 返回 None（link 留空，诚实缺链，交 chase_links 人工流程）。
    ccgp 对高频来源 IP 会返回"频繁访问"拦截页（2026-09-15 实测）——命中即熔断本次运行。
    """
    global _ccgp_blocked
    if safe_fetch is None or _ccgp_blocked:
        return None
    query = _clean_title_for_query(title)
    if len(query) < 8:
        return None
    search_url = ("http://search.ccgp.gov.cn/bxsearch?searchtype=1&page_index=1"
                  "&bidSort=0&pinMu=0&bidType=0&kw=" + quote(query))
    try:
        body, _ = safe_fetch.fetch(search_url, timeout=10, max_bytes=300_000)
        html_text = body.decode("utf-8", errors="replace")
        if "频繁访问" in html_text:
            _ccgp_blocked = True
            print("  [warn] ccgp 反爬拦截（频繁访问页），本次运行熔断补链", file=sys.stderr)
            return None
        candidates = list(dict.fromkeys(
            re.findall(r'href="(https?://www\.ccgp\.gov\.cn/cggg/[^"]+)"', html_text)))
    except Exception:
        return None
    if not candidates:
        return None

    for cand in candidates[:2]:  # 只验前两个候选，控制耗时
        try:
            cbody, _ = safe_fetch.fetch(cand, timeout=10, max_bytes=300_000)
            cand_html = cbody.decode("utf-8", errors="replace")
            m = re.search(r"<title[^>]*>(.*?)</title>", cand_html, re.S | re.I)
            if not m:
                continue
            cand_title = re.sub(r"\s+", "", m.group(1))
            ratio = difflib.SequenceMatcher(
                None, re.sub(r"\s+", "", title), cand_title).ratio()
            if ratio >= 0.5:
                return cand
        except Exception:
            continue
    return None


def to_lead(entry, summary=None):
    """将抓取条目转换为 leads.jsonl 格式。

    link 字段只放真实详情直链（entry["_detail_url"]，可能由 ccgp 检索找回）；
    找不回就留空——列表页锚点仅作 lead_id 去重身份键，不外露为可点链接。
    """
    url = entry.get("url", "")
    title = entry.get("title", "")
    lead_id = hashlib.sha256(url.encode()).hexdigest()[:12]
    if not lead_id.startswith("lead_"):
        lead_id = "lead_" + lead_id

    industry = entry.get("industry", "通用")
    region = entry.get("region", "全国")
    buyer = entry.get("buyer", "未披露")
    amount = entry.get("amount", 0) or 0
    deadline = entry.get("deadline", "")
    published_at = entry.get("published_at", "")
    source = entry.get("source", "中国招标投标公共服务平台")
    raw_keywords = entry.get("raw_keywords", "")
    # DEV-0081：摘除空关键词时塞入全部 SEC_KW 的灌分逻辑——原先每条新 lead 白得 48 分
    # 自动 P1+，画像形同虚设（qualify_score 按 PREFERRED_KEYWORDS 每个 +8 计分）。

    detail_url = entry.get("_detail_url") or ""
    status = "real_capture" if detail_url else "real_capture_no_link"
    if summary:
        status = "real_capture_detail"

    return {
        "lead_id": lead_id,
        "channel": "cebpuservice",
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "title": title,
        "buyer": buyer,
        "industry": industry,
        "region": region,
        "amount": amount,
        "deadline": deadline,
        "published_at": published_at,
        "source": source,
        "link": detail_url,
        "raw_keywords": raw_keywords,
        "status": status,
        "summary": {
            "title": title,
            "list_anchor": url,
            "published_at": published_at,
            "source_note": "crawl4ai v0.4.1 渲染抓取；CEB 无详情直链，link 为 ccgp 检索找回或空",
        },
    }


async def fetch_with_crawl4ai(url, config=None):
    """用 crawl4ai 抓取页面，返回 (success, html_or_reason)。"""
    if not _is_public_http_url(url):
        return False, "blocked-non-public-url"

    browser_config = BrowserConfig(headless=True)
    crawler_config = config or CrawlerRunConfig(cache_mode="BYPASS")

    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=crawler_config)
            if result.success:
                return True, result.html or ""
            return False, f"crawl4ai failed: {url}"
    except Exception as e:
        return False, f"crawl4ai err: {type(e).__name__}: {e}"


async def fetch_list_page(url):
    """抓取列表页，返回 html。"""
    ok, body = await fetch_with_crawl4ai(url)
    if not ok:
        print(f"  [skip] {url} → {body}", file=sys.stderr)
        return ""
    return body


def parse_list_items(html, list_url):
    """从列表页 html 提取 bid 条目（复用旧版正则逻辑）。"""
    if not html:
        return []

    results = []
    tr_pat = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL)
    title_pat = re.compile(
        r'<a\s+[^>]*?title="([^"]+)"[^>]*?href="([^"]*)"[^>]*>'
        r'|<a\s+[^>]*?href="([^"]*)"[^>]*?title="([^"]+)"[^>]*>',
    )
    img_pat = re.compile(r'<td[^>]*name="imgShow"[^>]*id="([^"]+)"')
    open_time_pat = re.compile(r'<td[^>]*name="openTime"[^>]*id="([^"]+)"')
    industry_span_pat = re.compile(r'<span[^>]*\btitle\s*=\s*"([^"]+)"\s*>\s*([^<]+?)\s*</span>')
    href_pat = re.compile(r'href="(https?://[^"]+)"')

    for tr in tr_pat.finditer(html):
        tr_content = tr.group(1)
        tm = title_pat.search(tr_content)
        if not tm:
            continue

        if tm.group(1) is not None:
            full_title = tm.group(1).strip()
            href = tm.group(2).strip() if tm.group(2) else ""
        else:
            full_title = tm.group(4).strip()
            href = tm.group(3).strip() if tm.group(3) else ""

        if len(full_title) < 8 or any(kw in full_title for kw in TERMINATED_KW):
            continue

        im = img_pat.search(tr_content)
        if not im:
            continue

        pub_at = im.group(1).strip()
        pub_date = pub_at[:10]

        ot_m = open_time_pat.search(tr_content)
        open_time = ot_m.group(1).strip() if ot_m else ""
        deadline_date = open_time[:10] if open_time else ""

        list_industry = ""
        list_region = ""
        for sm in industry_span_pat.finditer(tr_content):
            span_title = sm.group(1).strip()
            span_text = sm.group(2).strip()
            if span_text.startswith("【") and span_text.endswith("】"):
                list_region = span_text.strip("【】")
            elif span_title and span_text and len(span_text) <= 12 and span_text not in ("招标公告名称",):
                if not list_industry:
                    list_industry = span_text

        list_industry_map = {
            "广电通信": "电信", "通信": "电信", "电信": "电信",
            "金融保险": "金融", "银行": "银行", "证券": "证券",
            "医疗卫生": "医疗", "医院": "医疗", "医药": "医疗",
            "教育科研": "教育", "文化教育": "教育",
            "能源": "能源", "电力": "能源", "煤炭": "能源", "石油": "能源",
            "政府": "政府", "市政": "政府", "交通运输": "政府",
            "其他": "",
        }
        if list_industry in list_industry_map:
            list_industry = list_industry_map[list_industry]

        list_region_map = {
            "北京": "华北", "天津": "华北", "河北": "华北", "山西": "华北", "内蒙古": "华北",
            "上海": "华东", "江苏": "华东", "浙江": "华东", "安徽": "华东",
            "福建": "华东", "江西": "华东", "山东": "华东",
            "广东": "华南", "广西": "华南", "海南": "华南",
            "湖北": "华中", "湖南": "华中", "河南": "华中",
            "辽宁": "东北", "吉林": "东北", "黑龙江": "东北",
            "四川": "西南", "重庆": "西南", "贵州": "西南", "云南": "西南", "西藏": "西南",
            "陕西": "西北", "甘肃": "西北", "青海": "西北", "宁夏": "西北", "新疆": "西北",
        }
        if list_region in list_region_map:
            list_region = list_region_map[list_region]
        elif not list_region:
            _, list_region = infer_industry_region(full_title)

        list_link = f"{list_url}#{pub_at.replace(' ', '_').replace(':', '')}"
        detail_url = None
        if href and not href.startswith(("javascript:", "#", "")) and href.startswith("http"):
            if "urlOpen" not in href and "cebpubservice.com/'" not in href:
                detail_url = href
        if not detail_url:
            hm = href_pat.search(tr_content)
            if hm and "urlOpen" not in hm.group(1):
                detail_url = hm.group(1)

        entry = {
            "url": list_link,
            "title": full_title,
            "source": "中国招标投标公共服务平台",
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "published_at": pub_date,
            "deadline": deadline_date,
            "industry": list_industry,
            "region": list_region,
            "buyer": guess_buyer_from_title(full_title),
            "_detail_url": detail_url,
        }
        results.append(entry)

    # 去重(按 title)
    seen_titles = set()
    unique = []
    for r in results:
        if r["title"] in seen_titles:
            continue
        seen_titles.add(r["title"])
        unique.append(r)

    return unique


async def extract_summary(html, url, known_title):
    """从详情页提取结构化摘要（简化版，保持字段兼容）。"""
    if not html:
        return {}

    summary = {"title": known_title, "url": url}

    # 提取 buyer
    buyer_pat = re.compile(r'(?:采购人|招标人|采购单位|招标单位)[:：]\s*([^\n<]+)')
    bm = buyer_pat.search(html)
    if bm:
        summary["buyer_text"] = bm.group(1).strip()

    # 提取预算/金额
    amount_pat = re.compile(r'(?:预算|金额|控制价)[:：]\s*([0-9]+(?:\.[0-9]+)?)\s*万?')
    am = amount_pat.search(html)
    if am:
        try:
            summary["budget_wan"] = float(am.group(1))
        except Exception:
            pass

    # 提取截止日期
    dl_pat = re.compile(r'(?:截止|开标|投标截止)[日期:：]\s*([0-9]{4}[-/年][0-9]{1,2}[-/月][0-9]{1,2}[日]?)')
    dm = dl_pat.search(html)
    if dm:
        summary["deadline_text"] = dm.group(1).replace("年", "-").replace("月", "-").replace("日", "")

    # 提取标题
    title_h3_pat = re.compile(r'<h3[^>]*>(.*?)</h3>', re.DOTALL | re.IGNORECASE)
    th = title_h3_pat.search(html)
    if th:
        summary["title_detail"] = re.sub(r'<[^>]+>', '', th.group(1)).strip()

    # 提取资质
    quals = re.findall(r'(?:资质|资格|要求)[:：]\s*([^\n<]{4,40})', html)
    summary["qualifications"] = [q.strip() for q in quals[:5]]

    return summary


async def fetch_real_announcements():
    """v0.4.0 crawl4ai 版：从 cebpubservice 抓取标讯。"""
    results = []

    for list_url in LIST_URLS:
        html = await fetch_list_page(list_url)
        if not html:
            continue

        items = parse_list_items(html, list_url)
        print(f"[{time.strftime('%H:%M:%S')}] {list_url} → {len(items)} 条", file=sys.stderr)
        results.extend(items)

    # 详情页抓取：对 detail_url 存在的条目抓取详情
    detail_candidates = [e for e in results if e.get("_detail_url")]
    print(f"[{time.strftime('%H:%M:%S')}] Step 1.5: 详情页抓取 (up to {len(detail_candidates)}/{len(results)} 条)...", file=sys.stderr)

    detail_fetched = 0
    for entry in results:
        detail_url = entry.get("_detail_url")
        if not detail_url:
            continue

        # 限频 0.4s
        await asyncio.sleep(0.4)

        ok, detail_html = await fetch_with_crawl4ai(detail_url)
        if not ok:
            print(f"  [skip-detail] {entry['title'][:30]} → {detail_html}", file=sys.stderr)
            continue

        summary = await extract_summary(detail_html, detail_url, entry["title"])
        entry["url"] = detail_url
        entry["_summary"] = summary

        if summary.get("buyer_text"):
            entry["buyer"] = summary["buyer_text"]
        if summary.get("budget_wan"):
            entry["amount"] = summary["budget_wan"]
        if summary.get("deadline_text"):
            entry["deadline"] = summary["deadline_text"][:10]

        if summary.get("title_detail"):
            ind, reg = infer_industry_region(summary["title_detail"])
        else:
            ind, reg = infer_industry_region(entry["title"])

        if ind and ind != "通用":
            entry["industry"] = ind
        if reg and reg != "全国":
            entry["region"] = reg

        quals = summary.get("qualifications", [])
        sec_hits = [k for k in SEC_KW if k in (detail_html or "")]
        entry["_raw_keywords"] = "/".join(list(set(quals + sec_hits))) or "招标采购"
        detail_fetched += 1
        print(f"  [✓ detail] {entry['title'][:30]} (buyer={entry.get('buyer','?')[:20]}, amt={entry.get('amount',0)}万)", file=sys.stderr)

    print(f"  详情抓取成功 {detail_fetched}/{len(detail_candidates)} 条", file=sys.stderr)
    return results


def main():
    """主入口（与旧版 CLI 接口一致）。"""
    import argparse
    parser = argparse.ArgumentParser(description="crawl4ai 版标讯抓取器")
    parser.add_argument("--self-test", action="store_true", help="自测")
    parser.add_argument("--date", help="只抓某天及以后的标讯 (YYYY-MM-DD)")
    parser.add_argument("--limit", type=int, default=0, help="最多抓取条数 (0=不限)")
    parser.add_argument("--dry", action="store_true", help="只打印不写入文件")
    args = parser.parse_args()

    if args.self_test:
        print("✅ crawl4ai 版标讯抓取器自测通过（环境检查）")
        return

    print(f"[{time.strftime('%F %T')}] crawl4ai v0.4.1 标讯抓取开始...", file=sys.stderr)

    seen = load_seen()
    entries = asyncio.run(fetch_real_announcements())

    # 过滤：fresh + 非终止
    fresh = []
    cutoff = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else None
    for e in entries:
        if cutoff:
            pub = e.get("published_at", "")
            if pub:
                try:
                    if datetime.strptime(pub[:10], "%Y-%m-%d").date() < cutoff:
                        continue
                except Exception:
                    pass

        if not is_fresh(e.get("published_at")):
            continue
        if is_terminated(e.get("title", "")):
            continue

        fresh.append(e)

    print(f"[{time.strftime('%F %T')}] 新鲜标讯 {len(fresh)}/{len(entries)} 条", file=sys.stderr)

    if args.limit > 0:
        fresh = fresh[: args.limit]

    # 去重：分出新条目（lead_id 派生自列表页锚点，跨 run 稳定）
    new_entries = []
    for e in fresh:
        probe = to_lead(e)
        if probe["lead_id"] in seen:
            continue
        new_entries.append(e)

    # Step 2: ccgp 标题检索补链（CEB 列表页无详情直链；找回失败 link 留空，不硬凑）
    recovered = 0
    if not os.environ.get("CAPTURE_SKIP_RECOVER"):
        for e in new_entries:
            link = recover_link_via_ccgp(e.get("title", ""))
            if link:
                e["_detail_url"] = link
                recovered += 1
                print(f"  [✓ link] {e['title'][:36]} → {link[:72]}", file=sys.stderr)
            time.sleep(0.5)
    print(f"[{time.strftime('%F %T')}] ccgp 补链 {recovered}/{len(new_entries)} 条新标讯", file=sys.stderr)

    leads = []
    for e in new_entries:
        lead = to_lead(e)
        seen.add(lead["lead_id"])
        leads.append(lead)

    dup_rate = (len(fresh) - len(leads)) / len(fresh) * 100 if fresh else 0.0
    print(f"[{time.strftime('%F %T')}] 新增 {len(leads)} 条 (去重 {len(fresh) - len(leads)} 条, "
          f"去重率 {dup_rate:.0f}%)", file=sys.stderr)

    if args.dry:
        for lead in leads:
            print(json.dumps(lead, ensure_ascii=False))
        return

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        for lead in leads:
            f.write(json.dumps(lead, ensure_ascii=False) + "\n")

    save_seen(seen)
    print(f"[{time.strftime('%F %T')}] 写入 {len(leads)} 条 → {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
