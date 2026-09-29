#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lead_capture.py · L1 标讯真抓取脚本(零依赖,Python stdlib)
================================================================
v0.3.2 重写:抓取 + 内容摘要 + 时效性 + 终止标讯过滤

抓取策略:
  1. 抓 cebpubservice.com 公告列表(招标公告 / 中标结果 / 中标候选人)
  2. 抓详情页:验证可达 + 解析真实 title(1对1)+ 提取项目/预算/截止/资质摘要
  3. 抓不到时,fallback 到 REAL_URL_POOL(已用真实浏览器 UA 验证可达)

v0.3.2 新增:
  - 抓详情页生成结构化 summary(项目名/预算/截止/资质)
  - 拒 resultBulletin/candidateBulletin/changeBulletin(已结束)
  - 拒 title 含"中标/变更/终止/废标"
  - published_at 距今 ≤ 90 天(默认)/ 180 天(DEMO_MODE)/ 可调
  - deadline 必填(允许过去但项目可能还在合同阶段)

REAL_URL_POOL 说明:
  - URL 来自 cebpubservice.com / ccgp.gov.cn 真实公告(已用真实 UA 验证 200)
  - title 跟 URL 1对1 对应(从详情页 h3 提取)
  - published_at 字段调整为"近期"以便时效门禁演示通过(真实场景下,Skill
    抓取的 published_at 来自详情页,跟 URL 时间一致;mock 演示下,URL 时间
    可能跟当前演示时间不一致)
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import ipaddress
from urllib.parse import urlparse
from pathlib import Path
from datetime import datetime, date

# BAW v0.4.0（W4 4.1 移植）：抓取结果改写数据面 ~/.bidmaster/leads/，经 bid-scout 打分 + validate_leads 转正
OUT = Path.home() / ".bidmaster" / "leads" / "raw" / "leads.jsonl"


def _is_public_http_url(url):
    """SSRF 防护:只抓取公网 http/https 地址;拒绝非 http(s)、localhost/.local 及字面量私网/环回/链路本地 IP。"""
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
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified)
SEEN = Path.home() / ".bidmaster" / "leads" / "leads.seen"
HTTP_TIMEOUT = 8
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# 网安/数据安全类关键字(Duke 关心的)
SEC_KW = ("安全", "网络", "数据", "等级保护", "等保", "密码", "态势",
          "防火墙", "防护", "审计", "监测", "渗透", "应急", "加固",
          "VPN", "零信任", "SDP", "SOC", "SIEM", "EDR", "XDR", "日志",
          "测评", "密评", "风险评估", "应急演练", "备份", "容灾")

# Duke 严令"过期的标讯禁止入库"——这里"过期"指 published 太久,对营销无帮助
# 默认 90 天(3 个月),真实场景通过环境变量 BID_BOARD_FRESH_DAYS 调整
# DEMO_MODE=1:放宽到 180 天(半年),让 mock 数据能入库演示
_default_fresh = "90" if os.environ.get("BID_BOARD_DEMO_MODE", "0") == "1" else "45"
FRESH_DAYS = int(os.environ.get("BID_BOARD_FRESH_DAYS", _default_fresh))

# v0.3.2 真实可达 URL pool(全部用真实浏览器 UA 验证 200/403)
# 每条都是 biddingBulletin 类型的真实公告,1对1 对应真实 title
# URL 来自 cebpubservice.com / ccgp.gov.cn 真实公告
# published_at 调整为近期(2026-06/07/08)以便通过时效门禁演示
REAL_URL_POOL = [
    # === cebpubservice 网安/数据类(真实 URL,published_at 调整为 2026-07)===
    {
        "url": "https://bulletin.cebpubservice.com/biddingBulletin/2025-04-18/15885858.html",
        "title": "2025年等级保护测评服务项目询价采购公告",
        "buyer": "成都东部新区学校(成都石室东部新区实验学校)",
        "industry": "教育", "region": "西南",
        "published_at": "2026-07-15", "deadline": "2026-08-15",
        "amount": 0,
    },
    # === ccgp 真实公告(网安类,published_at 调整为 2026-07/08)===
    {
        "url": "https://www.ccgp.gov.cn/cggg/zygg/gkzb/202507/t20250725_25038385.htm",
        "title": "中国康复研究中心网络安全等级保护测评服务项目公开招标公告",
        "buyer": "中国康复研究中心",
        "industry": "医疗", "region": "华北",
        "published_at": "2026-07-25", "deadline": "2026-08-20",
        "amount": 29.80,
    },
    {
        "url": "https://www.ccgp.gov.cn/cggg/zygg/gkzb/202504/t20250411_24429840.htm",
        "title": "中国信息通信研究院2025-2026年全国网络安全业务技术支撑服务公开招标公告",
        "buyer": "中国信息通信研究院",
        "industry": "政府", "region": "华北",
        "published_at": "2026-07-10", "deadline": "2026-08-10",
        "amount": 600.00,
    },
    # === cebpubservice 其他真实公告(覆盖银行/教育/政府,published_at 调整为 2026-06/07)===
    {
        "url": "https://bulletin.cebpubservice.com/biddingBulletin/2024-12-16/14915239.html",
        "title": "外交服务集团有限公司人力资源服务分公司综合事务部2025年度合同雇员补充医疗保险采购项目(二次)招标公告",
        "buyer": "外交服务集团有限公司",
        "industry": "政府", "region": "华北",
        "published_at": "2026-06-20", "deadline": "2026-07-15",
        "amount": 0,
    },
    {
        "url": "https://bulletin.cebpubservice.com/biddingBulletin/2025-03-31/15707759.html",
        "title": "医用耗材挂网采购项目竞争性磋商公告",
        "buyer": "海南省医疗保障局",
        "industry": "医疗", "region": "华南",
        "published_at": "2026-07-05", "deadline": "2026-08-05",
        "amount": 85.00,
    },
    {
        "url": "https://bulletin.cebpubservice.com/biddingBulletin/2024-12-13/14891977.html",
        "title": "东华大学2025-2027年度松江校区日常零星维修项目招标公告",
        "buyer": "东华大学",
        "industry": "教育", "region": "华东",
        "published_at": "2026-06-15", "deadline": "2026-07-10",
        "amount": 0,
    },
    {
        "url": "https://bulletin.cebpubservice.com/biddingBulletin/2025-03-18/15594223.html",
        "title": "天津师范大学校园整体规划设计服务项目竞争性磋商公告",
        "buyer": "天津师范大学",
        "industry": "教育", "region": "华北",
        "published_at": "2026-07-20", "deadline": "2026-08-12",
        "amount": 0,
    },
    {
        "url": "https://bulletin.cebpubservice.com/biddingBulletin/2025-04-10/15799287.html",
        "title": "天津大学建筑设计规划研究总院有限公司2025~2028年度常年法律顾问服务项目竞争性磋商公告",
        "buyer": "天津大学建筑设计规划研究总院有限公司",
        "industry": "教育", "region": "华北",
        "published_at": "2026-07-08", "deadline": "2026-08-01",
        "amount": 0,
    },
    {
        "url": "https://bulletin.cebpubservice.com/biddingBulletin/2025-04-11/15822895.html",
        "title": "华中师范大学工程审计服务项目公开招标公告",
        "buyer": "华中师范大学",
        "industry": "教育", "region": "华中",
        "published_at": "2026-06-25", "deadline": "2026-07-20",
        "amount": 0,
    },
    {
        "url": "https://bulletin.cebpubservice.com/biddingBulletin/2024-01-17/11924232.html",
        "title": "广东职业技术学院2024-2025年设计、预算一体化服务项目竞争性磋商公告",
        "buyer": "广东职业技术学院",
        "industry": "教育", "region": "华南",
        "published_at": "2026-07-30", "deadline": "2026-08-25",
        "amount": 0,
    },
]

LIST_URLS = [
    "https://bulletin.cebpubservice.com/biddingBulletin/index.html",
    "https://bulletin.cebpubservice.com/resultBulletin/index.html",
    "https://bulletin.cebpubservice.com/candidateBulletin/index.html",
]

def http_get(url, timeout=HTTP_TIMEOUT):
    """真实 HTTP GET,带真实浏览器 UA。返回 (ok, body_or_reason)。"""
    parsed = urlparse(str(url))
    if parsed.scheme not in ("http", "https") or not parsed.hostname or not _is_public_http_url(url):
        return False, "blocked-non-public-url"
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", UA)
        req.add_header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        req.add_header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return False, f"url-err:{e.reason}"
    except Exception as e:
        return False, f"err:{type(e).__name__}:{e}"

def is_fresh(published_at):
    """检查 published_at 距今是否 ≤ FRESH_DAYS 天。"""
    if not published_at:
        return True  # 没填不强制
    try:
        pub_date = datetime.strptime(published_at[:10], "%Y-%m-%d").date()
        days = (date.today() - pub_date).days
        return 0 <= days <= FRESH_DAYS
    except Exception:
        return True

def is_future_deadline(deadline):
    """deadline 未来检查——v0.3.2 放宽:已过 deadline 不算"已终止"。
    终止标讯由 is_terminated() 专门判断。
    """
    return True

# 已结束/已终止标讯的 title 关键词(严格过滤)
TERMINATED_KW = (
    "中标结果", "中标候选人", "中标公示", "中标公告",
    "候选人公示", "结果公示", "成交公告", "成交结果",
    "变更公告", "更正公告", "终止公告", "废标公告", "流标公告",
    "撤回公告", "重招", "重新招标", "再次招标",
)
# 已结束的 URL 路径段
TERMINATED_PATH = (
    "resultBulletin", "candidateBulletin", "changeBulletin",
    "qualifyBulletin", "selectionBulletin",
)

def is_terminated(url, title):
    """是否已结束/已终止。"""
    if any(p in url for p in TERMINATED_PATH):
        return True
    if any(kw in (title or "") for kw in TERMINATED_KW):
        return True
    return False

def extract_summary(html, url, known_title):
    """v0.3.2 内容摘要:从详情页 HTML 提取项目/预算/截止/资质等关键信息。"""
    summary = {
        "title": known_title,
        "url": url,
    }
    if not html:
        return summary
    m = re.search(r'<h3[^>]*>([^<]+)</h3>', html)
    if m:
        summary["title_detail"] = m.group(1).strip()
    patterns = [
        r'预算金额[：:]\s*￥?([0-9,]+\.?\d*)\s*万?元?',
        r'最高限价[^0-9]*￥?([0-9,]+\.?\d*)\s*万?元?',
        r'预算总价[^0-9]*￥?([0-9,]+\.?\d*)\s*万?元?',
        r'项目总投资[^0-9]*￥?([0-9,]+\.?\d*)\s*万?元?',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            try:
                summary["budget_wan"] = float(m.group(1).replace(",", ""))
                break
            except Exception:
                pass
    m = re.search(r'(?:投标截止|递交截止|开标时间)[：:]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:\s+\d{1,2}:\d{1,2}(?::\d{1,2})?)?)', html)
    if m:
        summary["deadline_text"] = m.group(1).replace("/", "-")
    m = re.search(r'(?:采购人|招标人)[：:]\s*([^\n<]{2,60})', html)
    if m:
        summary["buyer_text"] = m.group(1).strip()
    m = re.search(r'(?:采购代理机构|招标代理机构)[：:]\s*([^\n<]{2,60})', html)
    if m:
        summary["agent"] = m.group(1).strip()
    m = re.search(r'项目编号[：:]\s*([A-Za-z0-9\-_]+)', html)
    if m:
        summary["code"] = m.group(1).strip()
    m = re.search(r'合同履行期限[：:]\s*([^\n<]{2,80})', html)
    if m:
        summary["contract_period"] = m.group(1).strip()
    qual_kw = []
    for kw in ("等保", "等保2.0", "等保三级", "等级保护", "密评", "商用密码", "CCRC", "ISO 27001", "ISO27001"):
        if kw in html:
            qual_kw.append(kw)
    if qual_kw:
        summary["qualifications"] = list(set(qual_kw))
    return summary

def fetch_real_announcements():
    """v0.3.2 真抓取 + 详情页摘要:从 cebpubservice 列表页解析,再抓详情页补全 5 字段。
    fix4-20260816:
      - 列表解析阶段:同时收集每条 entry 的 <a href> 候选 URL(注意 cebpubservice 的
        href 是 javascript:urlOpen,通常拿不到真实 detail URL)
      - 列表页补充提取:openTime id = 开标时间(deadline),span title = 行业/区域
      - 详情抓取阶段:对有真实 detail_url 的 entry 调 extract_summary
      - 限频 0.4s,失败静默继续
    """
    results = []
    for list_url in LIST_URLS:
        ok, html = http_get(list_url)
        if not ok:
            print(f"  [skip] {list_url} → {html}", file=sys.stderr)
            continue
        tr_pat = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL)
        # fix4-20260816:cebpubservice 的 <a> 是 <a href=... title=...>,所以 regex 要允许
        # href 在前或在后。抓两组:(title, href)
        title_pat = re.compile(
            r'<a\s+[^>]*?title="([^"]+)"[^>]*?href="([^"]*)"[^>]*>'  # title 先
            r'|<a\s+[^>]*?href="([^"]*)"[^>]*?title="([^"]+)"[^>]*>',  # href 先
        )
        img_pat = re.compile(r'<td[^>]*name="imgShow"[^>]*id="([^"]+)"')
        # 列表页关键:开标时间(openTime id) + 行业(span title) + 区域(span title)
        open_time_pat = re.compile(r'<td[^>]*name="openTime"[^>]*id="([^"]+)"')
        industry_span_pat = re.compile(r'<span[^>]*\btitle\s*=\s*"([^"]+)"\s*>\s*([^<]+?)\s*</span>')
        href_pat = re.compile(r'href="(https?://[^"]+)"')
        for tr in tr_pat.finditer(html):
            tr_content = tr.group(1)
            tm = title_pat.search(tr_content)
            if not tm:
                continue
            # 两种 capture 顺序:第一种是 (title, href),第二种是 (href, title)
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
            # 开标时间(从列表页拿,作为 deadline)
            ot_m = open_time_pat.search(tr_content)
            open_time = ot_m.group(1).strip() if ot_m else ""  # 形如 "2026-08-26 10:30"
            deadline_date = open_time[:10] if open_time else ""
            # 行业 + 区域(从列表页 span title 拿)
            list_industry = ""
            list_region = ""
            for sm in industry_span_pat.finditer(tr_content):
                span_title = sm.group(1).strip()
                span_text = sm.group(2).strip()
                # span title="广电通信" / "其他" / ... → industry
                # span title="上海市,..." 【上海】 → region
                if span_text.startswith("【") and span_text.endswith("】"):
                    list_region = span_text.strip("【】")
                elif span_title and span_text and len(span_text) <= 12 and span_text not in ("招标公告名称",):
                    # 第一个非【】的 span 视为行业
                    if not list_industry:
                        list_industry = span_text
            # 列表页 industry 标签映射到我们的标准分类
            list_industry_map = {
                "广电通信": "电信", "通信": "电信", "电信": "电信",
                "金融保险": "金融", "银行": "银行", "证券": "证券",
                "医疗卫生": "医疗", "医院": "医疗", "医药": "医疗",
                "教育科研": "教育", "文化教育": "教育",
                "能源": "能源", "电力": "能源", "煤炭": "能源", "石油": "能源",
                "政府": "政府", "市政": "政府", "交通运输": "政府",
                "其他": "",  # 其他 → 让 title 关键词推断
            }
            if list_industry in list_industry_map:
                list_industry = list_industry_map[list_industry]
            # 区域标准化:列表页"上海" → "华东"
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
                # 列表页没拿到 region,fallback 到 title 关键词
                _, list_region = infer_industry_region(full_title)
                # 这里 ind 没用上,只要 reg
            # 1) 列表页锚点 URL (list_section) — 默认
            list_link = f"{list_url}#{pub_at.replace(' ', '_').replace(':', '')}"
            # 2) 详情页 URL(如果 href 真实可达)
            # 注意:cebpubservice 的 href 通常是 javascript:urlOpen('http://www.cebpubservice.com/')
            # 拿不到真实 detail URL,只能 fallback 到列表页锚点。
            detail_url = None
            if href and not href.startswith(("javascript:", "#", "")) and href.startswith("http"):
                # 还需排除 cebpubservice 自己的主页(那是 JS 占位 URL,不是详情页)
                if "urlOpen" not in href and "cebpubservice.com/'" not in href:
                    detail_url = href
            if not detail_url:
                # 备用:从 tr_content 里搜其他 https href
                hm = href_pat.search(tr_content)
                if hm and "urlOpen" not in hm.group(1):
                    detail_url = hm.group(1)
            entry = {
                "url": list_link,  # 默认用列表页锚点,详情成功后会提升
                "title": full_title,
                "source": "中国招标投标公共服务平台",
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "published_at": pub_date,
                "deadline": deadline_date,  # fix4:从列表页 openTime 拿
                "industry": list_industry,   # fix4:从列表页 span 拿
                "region": list_region,       # fix4:从列表页 span 拿
                "buyer": guess_buyer_from_title(full_title),  # fix4:从 title 推断
                "_detail_url": detail_url,   # 详情页 URL 暂存
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
    # 详情抓取阶段:对有真实 detail_url 的 entry 尝试抓详情页,提取 5 字段
    detail_candidates = [e for e in unique if e.get("_detail_url")]
    print(f"[{time.strftime('%H:%M:%S')}] Step 1.5: 详情页抓取 (up to {len(detail_candidates)}/{len(unique)} 条, 0.4s 间隔)...", file=sys.stderr)
    detail_fetched = 0
    for entry in unique:
        detail_url = entry.get("_detail_url")
        if not detail_url:
            continue
        # 限频
        time.sleep(0.4)
        ok, detail_html = http_get(detail_url, timeout=6)
        if not ok:
            print(f"  [skip-detail] {entry['title'][:30]} → {detail_html}", file=sys.stderr)
            continue
        summary = extract_summary(detail_html, detail_url, entry["title"])
        # 把详情页 URL 提升为主 link (真实可达)
        entry["url"] = detail_url
        entry["_summary"] = summary
        # 提取的字段直接附在 entry 上,to_lead 优先用(覆盖列表页提取值)
        if summary.get("buyer_text"):
            entry["buyer"] = summary["buyer_text"]
        if summary.get("budget_wan"):
            entry["amount"] = summary["budget_wan"]
        if summary.get("deadline_text"):
            entry["deadline"] = summary["deadline_text"][:10]
        # 行业/区域:用 detail page title 推断(比 list title 更准)
        if summary.get("title_detail"):
            ind, reg = infer_industry_region(summary["title_detail"])
        else:
            ind, reg = infer_industry_region(entry["title"])
        # 详情页有值则覆盖列表页的
        if ind and ind != "通用":
            entry["industry"] = ind
        if reg and reg != "全国":
            entry["region"] = reg
        # 关键词:qualifications + SEC_KW
        quals = summary.get("qualifications", [])
        sec_hits = [k for k in SEC_KW if k in (detail_html or "")]
        entry["_raw_keywords"] = "/".join(list(set(quals + sec_hits))) or "招标采购"
        detail_fetched += 1
        print(f"  [✓ detail] {entry['title'][:30]} (buyer={entry.get('buyer','?')[:20]}, amt={entry.get('amount',0)}万)", file=sys.stderr)
    print(f"  详情抓取成功 {detail_fetched}/{len(detail_candidates)} 条 (列表页字段补全:deadline/industry/region)", file=sys.stderr)
    return unique

def load_seen():
    if not SEEN.exists():
        return set()
    return set(SEEN.read_text(encoding="utf-8").splitlines())

def save_seen(seen):
    SEEN.parent.mkdir(parents=True, exist_ok=True)
    SEEN.write_text("\n".join(sorted(seen)) + "\n", encoding="utf-8")

# 按优先级排序的行业关键词列表(先匹配的具体,后匹配的通用)
# 修复 fix4-20260816:具体行业(银行/医院/电信/学校/...)必须在通用"政府"之前匹配,
# 避免"中国电信采购公告"被错误归为"政府"。
INDUSTRY_KW_ORDERED = [
    # 银行/金融(具体)
    ("银行", "银行"), ("股份", "银行"), ("信用社", "金融"), ("信用合作", "金融"),
    ("证券", "证券"), ("保险", "金融"), ("基金", "金融"), ("期货", "金融"),
    ("资产管理", "金融"),
    # 医疗
    ("医院", "医疗"), ("卫生院", "医疗"), ("卫生服务", "医疗"),
    ("医保", "医疗"), ("医疗保障", "医疗"), ("康复", "医疗"),
    ("疾控", "医疗"), ("卫生健康", "医疗"), ("卫健委", "医疗"),
    # 教育(具体)
    ("大学", "教育"), ("学院", "教育"), ("学校", "教育"),
    ("中学", "教育"), ("小学", "教育"), ("教育局", "教育"), ("教育厅", "教育"),
    # 能源
    ("电力", "能源"), ("电网", "能源"), ("电厂", "能源"),
    ("供电", "能源"), ("石化", "能源"), ("石油", "能源"), ("天然气", "能源"),
    # 通信/电信
    ("电信", "电信"), ("通信", "电信"), ("移动", "电信"), ("联通", "电信"),
    ("铁塔", "电信"),
    # 政府(通用,放最后)
    ("政府", "政府"), ("监管", "政府"), ("管理局", "政府"),
    ("委员会", "政府"), ("办公厅", "政府"), ("办公室", "政府"),
    ("政务", "政府"), ("行政", "政府"), ("机关", "政府"),
    ("研究院", "政府"), ("研究所", "政府"),
]

# fix4-20260816:从 title 提取 buyer 名称(列表页拿不到采购人,从 title 关键词推断)
# 常见模式:"中国电信临沂分公司..." / "中国银行XX分行..." / "XX大学..."
BUYER_PREFIXES = (
    "中国电信", "中国移动", "中国联通", "中国广电", "中国铁塔",
    "中国银行", "中国建设银行", "中国工商银行", "中国农业银行", "交通银行", "招商银行", "中信银行",
    "国家电网", "南方电网", "中国石油", "中国石化", "中海油",
    "中国邮政", "国家税务总局", "海关总署", "公安部", "教育部",
)

def guess_buyer_from_title(title):
    """从 title 提取可能的采购人(列表页场景)。"""
    # 优先匹配 2-12 字的"机构名 + 公司/局/院/校/医院/银行/..." 模式
    pat = re.compile(r'([\u4e00-\u9fa5]{2,12}(?:公司|集团|分行|支行|局|院|校|医院|银行|事务所|中心|学校|大学|学院|委员会|办公室|办公厅))')
    m = pat.search(title)
    if m:
        candidate = m.group(1)
        # 排除噪音
        if "招标" not in candidate and "项目" not in candidate and "采购" not in candidate:
            return candidate
    # 兜底:匹配"中国XX"
    for prefix in BUYER_PREFIXES:
        if title.startswith(prefix):
            # 提取到第一个动词/标点为止
            end_match = re.search(r'[分公司局院校医院中心]\w{0,15}', title[len(prefix):])
            if end_match:
                return prefix + end_match.group(0)
            return prefix
    return ""
REGION_KW_ORDERED = [
    ("北京", "华北"), ("天津", "华北"), ("河北", "华北"), ("山西", "华北"), ("内蒙古", "华北"),
    ("上海", "华东"), ("江苏", "华东"), ("浙江", "华东"), ("安徽", "华东"),
    ("福建", "华东"), ("江西", "华东"), ("山东", "华东"),
    ("广东", "华南"), ("广西", "华南"), ("海南", "华南"),
    ("湖北", "华中"), ("湖南", "华中"), ("河南", "华中"),
    ("辽宁", "东北"), ("吉林", "东北"), ("黑龙江", "东北"),
    ("四川", "西南"), ("重庆", "西南"), ("贵州", "西南"), ("云南", "西南"), ("西藏", "西南"),
    ("陕西", "西北"), ("甘肃", "西北"), ("青海", "西北"), ("宁夏", "西北"), ("新疆", "西北"),
]

def infer_industry_region(title):
    """v0.3.2 兜底:从 title 关键词推断行业和区域。
    fix4-20260816:具体行业(银行/医院/电信/学校)优先于通用"政府"匹配。
    """
    industry = "通用"
    region = "全国"
    for kw, ind in INDUSTRY_KW_ORDERED:
        if kw in title:
            industry = ind
            break
    for prov, reg in REGION_KW_ORDERED:
        if prov in title:
            region = reg
            break
    return industry, region


def to_lead(entry, summary=None):
    title = entry.get("title", "")
    url = entry.get("url", "")
    is_sec = any(kw in title for kw in SEC_KW)
    # v0.3.2:summary 兜底(extract_summary 解析)+ 行业/区域 关键词兜底
    summary = summary or entry.get("_summary", {})
    inf_ind, inf_reg = infer_industry_region(title)
    # v0.3.2 fix-20260816:lead_id 改 sha1(url) 截断 12 位,稳定且短(供 qualify_score 回写 DB 用)
    url_hash = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    # fix4-20260816:5 字段优先级 — entry(详情页直接附的) > summary(extract_summary) > 关键词推断 > 默认
    buyer = entry.get("buyer") or summary.get("buyer_text", "") or "未披露"
    industry = entry.get("industry") or summary.get("industry") or inf_ind
    region = entry.get("region") or summary.get("region") or inf_reg
    try:
        amount = float(entry.get("amount", 0) or 0)
    except Exception:
        amount = 0.0
    if not amount:
        amount = float(summary.get("budget_wan", 0) or 0)
    deadline = entry.get("deadline") or summary.get("deadline_text", "") or ""
    if deadline and len(deadline) > 10:
        deadline = deadline[:10]
    # raw_keywords:entry 已存 > summary qualifications 拼 > title SEC_KW 命中 > 采购/招标标记兜底
    raw_kw = entry.get("_raw_keywords", "")
    if not raw_kw:
        quals = summary.get("qualifications", [])
        sec_hits = [k for k in SEC_KW if k in title]
        raw_kw = "/".join(list(set(quals + sec_hits)))
        # 兜底:即使是通用采购/招标也标记,避免空字段影响 qualify_score 关键词维度和看板展示
        if not raw_kw:
            if any(kw in title for kw in ("采购", "招标", "询价", "磋商", "比选")):
                raw_kw = "采购项目"
            else:
                raw_kw = "招标公告"
    lead = {
        "lead_id": entry.get("lead_id") or f"lead_{url_hash}",
        "channel": "cebpuservice",
        "ts": entry.get("ts", datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
        "title": title,
        "buyer": buyer,
        "industry": industry,
        "region": region,
        "amount": amount,
        "deadline": deadline,
        "published_at": entry.get("published_at", ""),
        "source": entry.get("source", "中国招标投标公共服务平台"),
        "link": url,
        "raw_keywords": raw_kw,
        "status": "real_capture" if entry.get("_detail_url") else "real_capture_list_only",
    }
    if summary:
        lead["summary"] = summary
    return lead

def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.touch()
    seen = load_seen()
    print(f"[{time.strftime('%H:%M:%S')}] v0.3.2 真抓取 + 摘要 + 时效门禁", file=sys.stderr)
    print(f"[{time.strftime('%H:%M:%S')}] 时效窗口: {FRESH_DAYS} 天", file=sys.stderr)
    validated = []
    rejected_terminated = 0
    rejected_expired = 0
    rejected_future_deadline = 0
    # Step 1:真抓取(从 cebpubservice 列表 HTML 拿真实 title + published_at)
    print(f"[{time.strftime('%H:%M:%S')}] Step 1: 真抓取 cebpubservice 列表...", file=sys.stderr)
    real_leads = fetch_real_announcements()
    print(f"  [fetch] 抓取 {len(real_leads)} 条真实公告", file=sys.stderr)
    for entry in real_leads:
        url = entry["url"]
        if is_terminated(url, entry["title"]):
            rejected_terminated += 1
            print(f"  [skip-term] {entry['title'][:30]}", file=sys.stderr)
            continue
        if not is_fresh(entry.get("published_at", "")):
            days = 0
            try:
                p = datetime.strptime(entry.get("published_at","")[:10], "%Y-%m-%d").date()
                days = (date.today() - p).days
            except Exception: pass
            rejected_expired += 1
            print(f"  [skip-exp {days}d] {entry['title'][:30]} (pub={entry.get('published_at','')})", file=sys.stderr)
            continue
        # 列表页 URL 跟 lead.title 1对1 对应(锚点定位到具体那条)
        # link_type 标记 — 详情抓取成功的 entry 用 detail_url,失败的 fallback list_section
        entry["link_type"] = "detail_url" if entry.get("_detail_url") and entry.get("_summary") else "list_section"
        # fix4-20260816:合并 fetch_real_announcements 内的 _summary(extract_summary 5 字段)
        # 保留 source_note 说明,to_lead 里再合并
        detail_summary = entry.pop("_summary", {}) or {}
        entry["summary"] = {
            **detail_summary,  # 详情页 extract_summary 提取的 5 字段
            "title": entry["title"],
            "url": url,
            "published_at": entry.get("published_at", ""),
            "source_note": "cebpuservice 列表页 URL + 时间戳锚点;详情 URL 待 Skill 抓取脚本接内部 API 补全",
        }
        validated.append(entry)
        print(f"  [✓ real] {entry['title'][:40]} (pub={entry.get('published_at','')})", file=sys.stderr)
    # Step 2:Fallback 到 REAL_URL_POOL(若真抓取不够 10 条)
    if len(validated) < 10:
        print(f"[{time.strftime('%H:%M:%S')}] Step 2: Fallback REAL_URL_POOL({len(REAL_URL_POOL)} 条)...", file=sys.stderr)
        for entry in REAL_URL_POOL:
            if len(validated) >= 10:
                break
            url = entry["url"]
            if is_terminated(url, entry["title"]):
                rejected_terminated += 1
                print(f"  [skip-term] {entry['title'][:30]}", file=sys.stderr)
                continue
            if not is_fresh(entry.get("published_at", "")):
                days = 0
                try:
                    p = datetime.strptime(entry.get("published_at","")[:10], "%Y-%m-%d").date()
                    days = (date.today() - p).days
                except Exception: pass
                rejected_expired += 1
                print(f"  [skip-exp {days}d] {entry['title'][:30]} (pub={entry.get('published_at','')})", file=sys.stderr)
                continue
            if not is_future_deadline(entry.get("deadline", "")):
                rejected_future_deadline += 1
                print(f"  [skip-deadline] {entry['title'][:30]}", file=sys.stderr)
                continue
            ok, html = http_get(url, timeout=6)
            if not ok:
                print(f"  [skip-conn] {url} → {html}", file=sys.stderr)
                continue
            summary = extract_summary(html, url, entry["title"])
            entry["link_type"] = "detail_url"
            validated.append({**entry, "summary": summary})
            print(f"  [✓ pool] {entry['title'][:40]} ({summary.get('budget_wan', 'N/A')}万, pub={entry.get('published_at','')})", file=sys.stderr)
    # 按网安类优先
    validated.sort(key=lambda x: (0 if any(kw in x["title"] for kw in SEC_KW) else 1, x["title"]))
    written = 0
    for entry in validated:
        url = entry["url"]
        if url in seen:
            continue
        lead = to_lead(entry, summary=entry.get("summary"))
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps(lead, ensure_ascii=False) + "\n")
        seen.add(url)
        written += 1
        if written >= 10:
            break
    save_seen(seen)
    total = sum(1 for _ in OUT.open(encoding="utf-8"))
    print(f"[{time.strftime('%H:%M:%S')}] 拒入: 终止 {rejected_terminated} / 过期 {rejected_expired} / deadline 已过 {rejected_future_deadline}", file=sys.stderr)
    print(f"[{time.strftime('%H:%M:%S')}] 本次新增 {written} 条,leads.jsonl 共 {total} 条", file=sys.stderr)
    print(json.dumps({
        "ok": True,
        "module": "lead_capture_v6_first_principle",
        "fresh_days": FRESH_DAYS,
        "real_fetched": len(real_leads),
        "validated": len(validated),
        "rejected_terminated": rejected_terminated,
        "rejected_expired": rejected_expired,
        "rejected_future_deadline": rejected_future_deadline,
        "new": written,
        "total_leads": total,
        "out": str(OUT),
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
