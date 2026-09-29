#!/usr/bin/env python3
"""app/services/lead_gate.py · lead 质量门禁（自 server.py 533-1056 原样迁移，行为保真）

8+1 道门：必填字段 / URL 格式 / 拒搜索引擎 / 拒首页列表页 / 拒无详情路径 /
拒终止标讯 / 拒过期标讯 / 域名白名单 / 真实可达性（HEAD + 5min 缓存 + SSRF 防护）。
"""
import ipaddress
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .. import config

# Duke 要求:商机必须真实存在可访问,至少一个源才入库
ALLOWED_LINK_DOMAINS = (
    # 中国招标投标公共服务平台
    "cebpubservice.com",
    # 中国政府采购网
    "ccgp.gov.cn",
    # 深圳/北京/上海政府采购
    "zfcg.sz.gov.cn", "zfcg.beijing.gov.cn", "zfcg.sh.gov.cn",
    # 银行
    "bank.pingan.com", "pingan.com", "cmbchina.com", "pingan.cn",
    "abchina.com", "bosc.cn", "spdb.com.cn", "cib.com.cn", "cebbank.com",
    "cgbchina.com.cn", "hxb.com.cn", "citicbank.com", "csrc.gov.cn",
    # 证券/交易所
    "sse.com.cn", "szse.cn", "hkex.com.hk", "csrc.gov.cn", "sac.net.cn",
    # 能源/电网/油企
    "cnooc.com.cn", "buy.cnooc.com.cn", "sgcc.com.cn", "ecp.sgcc.com.cn",
    "csgcc.com.cn", "cpnn.com.cn", "shenhua.com.cn", "sinopec.com",
    "petrochina.com.cn",
    # 政府/部委
    "gov.cn", "miit.gov.cn", "mps.gov.cn", "mof.gov.cn", "moj.gov.cn",
    "ndrc.gov.cn", "samr.gov.cn", "cac.gov.cn", "12377.cn", "12321.cn",
    # 央企
    "sasac.gov.cn", "csrc.gov.cn",
    # 公共资源交易
    "ggzy.gov.cn", "ggzy.hebei.gov.cn", "ggzy.guizhou.gov.cn",
    # 第三方权威(招标雷达/剑鱼标讯)
    "zbldragon.com", "jiandy.com", "bidchance.com",
    # 港澳
    "gov.hk",
)
# 关键字白名单:netloc 含这些关键字的也算真实源(覆盖未列出的银行/政府子域名)
ALLOWED_KEYWORDS = (
    "bank", "gov.cn", "securities", "exchange", "sgcc", "cnooc",
    "cebpubservice", "ccgp", "zfcg", "pingan", "cmbchina",
    "cgbchina", "spdb", "cebbank", "hxb", "citicbank", "abchina",
    "bosc", "sse", "szse", "hkex", "ggzy", "sinopec", "petrochina",
    "shenhua", "mps", "miit", "mof", "moj", "ndrc", "samr", "cac",
    "12377", "12321", "sasac", "csrc", "sac", "bidchance", "zbldragon",
)

LINK_REACH_CACHE = {}        # url -> (ok_bool, reason_str, ts_float)
LINK_REACH_TTL = 300.0       # 5 分钟内同 URL 不重复探测
LINK_REACH_TIMEOUT = 3.5     # 单次探测超时
LINK_REACH_ENABLED = not config.SKIP_REACH


def is_public_http_url(link):
    """SSRF 防护:只允许探测公网 http/https 地址。"""
    try:
        p = urlparse(str(link))
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


def check_link_reachable(link, use_cache=True):
    """可达性门禁:HEAD 请求验证 link 真实可访问。403=反爬但存在（算可达）。"""
    if not LINK_REACH_ENABLED:
        return True, "skip(check disabled)"
    if not link:
        return False, "empty"
    parsed = urlparse(str(link))
    if parsed.scheme not in ("http", "https") or not parsed.hostname or not is_public_http_url(link):
        LINK_REACH_CACHE[link] = (False, "blocked-non-public-url", time.time())
        return False, "blocked-non-public-url"
    if use_cache and link in LINK_REACH_CACHE:
        ok, reason, ts = LINK_REACH_CACHE[link]
        if time.time() - ts < LINK_REACH_TTL:
            return ok, f"cached-{reason}"
    UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    try:
        req = urllib.request.Request(link, method="HEAD")
        req.add_header("User-Agent", UA)
        req.add_header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        req.add_header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")
        with urllib.request.urlopen(req, timeout=LINK_REACH_TIMEOUT) as resp:
            code = resp.status
            if 200 <= code < 400:
                LINK_REACH_CACHE[link] = (True, f"HTTP {code}", time.time())
                return True, f"HTTP {code}"
            LINK_REACH_CACHE[link] = (False, f"HTTP {code}", time.time())
            return False, f"HTTP {code}"
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:
            LINK_REACH_CACHE[link] = (True, f"HTTP {e.code}(redirect)", time.time())
            return True, f"HTTP {e.code}(redirect)"
        if e.code == 403:
            try:
                req = urllib.request.Request(link, method="GET")
                req.add_header("User-Agent", UA)
                req.add_header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
                req.add_header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")
                with urllib.request.urlopen(req, timeout=LINK_REACH_TIMEOUT) as resp:
                    code = resp.status
                    if 200 <= code < 400:
                        LINK_REACH_CACHE[link] = (True, f"GET-{code}", time.time())
                        return True, f"GET-{code}"
                    if code == 403:
                        LINK_REACH_CACHE[link] = (True, "GET-403(anti-bot)", time.time())
                        return True, "GET-403(anti-bot)"
                    LINK_REACH_CACHE[link] = (False, f"GET-{code}", time.time())
                    return False, f"GET-{code}"
            except urllib.error.HTTPError as e2:
                if 200 <= e2.code < 400:
                    LINK_REACH_CACHE[link] = (True, f"GET-{e2.code}", time.time())
                    return True, f"GET-{e2.code}"
                if e2.code == 403:
                    LINK_REACH_CACHE[link] = (True, "GET-403(anti-bot)", time.time())
                    return True, "GET-403(anti-bot)"
                LINK_REACH_CACHE[link] = (False, f"GET-{e2.code}", time.time())
                return False, f"GET-{e2.code}"
            except Exception as e2:
                LINK_REACH_CACHE[link] = (False, f"GET-err:{type(e2).__name__}", time.time())
                return False, f"GET-err:{type(e2).__name__}"
        if e.code == 405:
            try:
                req = urllib.request.Request(link, method="GET")
                req.add_header("User-Agent", UA)
                with urllib.request.urlopen(req, timeout=LINK_REACH_TIMEOUT) as resp:
                    code = resp.status
                    if 200 <= code < 400:
                        LINK_REACH_CACHE[link] = (True, f"GET-{code}", time.time())
                        return True, f"GET-{code}"
                    LINK_REACH_CACHE[link] = (False, f"GET-{code}", time.time())
                    return False, f"GET-{code}"
            except Exception as e2:
                LINK_REACH_CACHE[link] = (False, f"GET-err:{type(e2).__name__}", time.time())
                return False, f"GET-err:{type(e2).__name__}"
        LINK_REACH_CACHE[link] = (False, f"HTTP {e.code}", time.time())
        return False, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        LINK_REACH_CACHE[link] = (False, f"url-err:{e.reason}", time.time())
        return False, f"url-err:{e.reason}"
    except Exception as e:
        LINK_REACH_CACHE[link] = (False, f"err:{type(e).__name__}", time.time())
        return False, f"err:{type(e).__name__}"


# v0.3.2 严格门禁:禁止搜索引擎/首页/列表页——必须具体详情页 URL
SEARCH_ENGINES = (
    "bing.com", "www.bing.com", "cn.bing.com",
    "baidu.com", "www.baidu.com",
    "google.com", "www.google.com",
    "sogou.com", "www.sogou.com",
    "so.com", "www.so.com",
    "duckduckgo.com",
    "yandex.com",
)
LIST_PATH_PATTERNS = (
    "/index.html", "/index.htm", "/index.shtml",
    "/index", "/list", "/list.html", "/list.htm",
    "/search", "/search.html",
    "/home", "/home.html",
)


def is_search_engine_url(url):
    """Duke 严令禁止:Google hacking/搜索 URL 滥竽充数。"""
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc in SEARCH_ENGINES:
            return True
        if any(q in url.lower() for q in ("?q=", "?s=", "?keywords=", "?search=", "?query=", "?wd=", "?ie=")):
            return True
        return False
    except Exception:
        return False


def is_list_or_homepage_url(url):
    """拒绝平台首页/列表页当详情页；例外:列表页 + 锚点（#时间戳_序号 定位具体公告）。"""
    try:
        u = urlparse(url)
        if u.fragment and ("_" in u.fragment or "-" in u.fragment):
            return False
        path = u.path.rstrip("/")
        if path == "":
            return True
        if any(path.endswith(p) for p in LIST_PATH_PATTERNS):
            return True
        return False
    except Exception:
        return False


def has_detail_path(url):
    """URL 必须有具体详情路径段（1对1 对应标讯）；例外:列表页 + 锚点。"""
    try:
        u = urlparse(url)
        if u.fragment and ("_" in u.fragment or "-" in u.fragment):
            return True
        path = u.path.rstrip("/")
        parts = [p for p in path.split("/") if p]
        if len(parts) < 2:
            return False
        last = parts[-1].lower()
        if not ("." in last or last.isdigit()):
            return False
        stem = last.split(".")[0] if "." in last else last
        if stem in ("index", "list", "home", "search"):
            return False
        return True
    except Exception:
        return False


# 终止/已结束标讯门禁:URL 路径含"中标/结果/候选人/变更/终止"等 → 拒入
TERMINATED_BULLETIN_TYPES = (
    "resultBulletin",      # 中标结果
    "candidateBulletin",   # 中标候选人
    "changeBulletin",      # 变更公告
    "qualifyBulletin",     # 资格预审结果
    "selectionBulletin",   # 中选公告
)
TERMINATED_TITLE_KEYWORDS = (
    "中标结果", "中标候选人", "中标公示", "中标公告",
    "候选人公示", "结果公示", "成交公告", "成交结果",
    "变更公告", "更正公告", "终止公告", "废标公告", "流标公告",
    "撤回公告", "重招", "重新招标", "再次招标",
)


def is_terminated_bulletin(url, title):
    """终止标讯门禁：URL 路径与 title 双重判断。"""
    try:
        u = urlparse(url)
        path_lower = u.path.lower()
        for t in TERMINATED_BULLETIN_TYPES:
            if t.lower() in path_lower:
                return True, f"URL 是{t}(已结束)"
        for kw in TERMINATED_TITLE_KEYWORDS:
            if kw in (title or ""):
                return True, f"title 含'{kw}'(已结束)"
        return False, ""
    except Exception:
        return False, ""


def is_expired(lead):
    """时效门禁：published_at 距今 > N 天 → 拒入。deadline 已过不拒（项目可能仍在公示期）。"""
    from datetime import datetime, date
    try:
        today = date.today()
        pub = (lead.get("published_at") or "").strip()
        if pub:
            pub_date = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    pub_date = datetime.strptime(pub[:19], fmt).date()
                    break
                except ValueError:
                    continue
            if pub_date:
                days_old = (today - pub_date).days
                if days_old > config.LEAD_FRESH_DAYS:
                    return True, f"published_at 距今 {days_old} 天(>{config.LEAD_FRESH_DAYS} 天,已过期)"
                if days_old < 0:
                    return True, f"published_at {pub} 是未来时间(异常)"
        return False, ""
    except Exception as e:
        return False, f"err:{e}"


def validate_lead_quality(lead):
    """质量门禁：校验 lead 是否真实可入库。返回 (ok, reason)。"""
    # 1. 必填字段
    title = (lead.get("title") or "").strip()
    buyer = (lead.get("buyer") or "").strip()
    source = (lead.get("source") or lead.get("channel") or "").strip()
    link = (lead.get("link") or "").strip()
    if not title:
        return False, "缺 title"
    # buyer 留空时用 source 兜底（真抓取路径可能没 buyer 字段）
    if not buyer or buyer in ("待 AI 抽取", "未知", "?"):
        buyer = source
        if not buyer:
            return False, f"buyer 无效({buyer!r})且 source 也为空"
    if not source:
        return False, "缺 source"
    if not link:
        return False, "缺 link(无源则不入库)"
    # 2. URL 格式
    try:
        u = urlparse(link)
        if u.scheme not in ("http", "https"):
            return False, f"link scheme 非法({u.scheme!r})"
        if not u.netloc:
            return False, "link 缺 netloc"
    except Exception as e:
        return False, f"link parse 失败({e})"
    # 3. 拒绝搜索引擎（Google hacking/搜索查询 URL）
    if is_search_engine_url(link):
        return False, "link 是搜索引擎/搜索 URL(Duke 严令禁止,必须直接标讯详情页)"
    # 4. 拒绝平台首页/列表页
    if is_list_or_homepage_url(link):
        return False, "link 是平台首页/列表页(必须具体详情页 URL,1对1 对应标讯)"
    # 5. 拒绝无具体路径段的 URL
    if not has_detail_path(link):
        return False, "link 缺具体详情路径(必须含 ID/编号等具体段,1对1 对应)"
    # 6. 终止标讯门禁
    is_term, term_reason = is_terminated_bulletin(link, title)
    if is_term:
        return False, f"已终止标讯({term_reason})"
    # 7. 时效门禁
    is_exp, exp_reason = is_expired(lead)
    if is_exp:
        return False, f"过期标讯({exp_reason})"
    # 8. 域名白名单
    netloc = u.netloc.lower().lstrip("www.")
    if netloc in ALLOWED_LINK_DOMAINS:
        pass
    elif any(kw in netloc for kw in ALLOWED_KEYWORDS):
        pass
    else:
        return False, f"link 域名未在白名单({netloc})"
    # 9. 真实可达性（HEAD + 缓存）
    ok_reach, reach_reason = check_link_reachable(link)
    if not ok_reach:
        return False, f"link 不可达({reach_reason})"
    return True, f"已验证详情页可达({reach_reason})"
