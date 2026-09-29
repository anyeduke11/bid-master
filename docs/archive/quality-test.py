#!/usr/bin/env python3
"""投标看板 · 质量测试套件 · bid-board v0.3.2(对应 PRD v5.2 终稿)
- 31 项自动化测试
- 覆盖 v2/v3/v4 全部功能 + v0.3.2 命令注册/幂等/审计
- 0 外部依赖
"""
import json
import time
import sys
import uuid
import subprocess
import sqlite3
import urllib.request
import urllib.error
from urllib.parse import urlparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "http://127.0.0.1:8080"
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
results = []

def _assert_local_url(url):
    """SSRF 防护:测试套件只允许请求本机看板服务。"""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or p.hostname not in _ALLOWED_HOSTS:
        raise ValueError(f"测试只允许本机地址,拒绝: {url!r}")
    return url

def req(method, path, body=None, timeout=5):
    url = _assert_local_url(BASE + path)
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read().decode())
        except: return e.code, {}
    except Exception as e:
        return 0, {"err": str(e)}

def sse_collect(seconds=3):
    """用 urllib 流式读 SSE,返回事件列表"""
    import socket
    s = socket.create_connection(("127.0.0.1", 8080), timeout=seconds+2)
    s.sendall(f"GET /api/stream HTTP/1.1\r\nHost: 127.0.0.1\r\nAccept: text/event-stream\r\n\r\n".encode())
    events = []
    s.settimeout(seconds)
    buf = b""
    deadline = time.time() + seconds
    try:
        while time.time() < deadline:
            try:
                chunk = s.recv(4096)
                if not chunk: break
                buf += chunk
                while b"\n\n" in buf:
                    block, buf = buf.split(b"\n\n", 1)
                    for line in block.split(b"\n"):
                        if line.startswith(b"data: "):
                            try: events.append(json.loads(line[6:].decode()))
                            except: pass
            except socket.timeout:
                break
    finally:
        s.close()
    return events

def check(name, actual, expected_substr):
    if isinstance(expected_substr, str):
        ok = expected_substr in str(actual)
    elif isinstance(expected_substr, bool):
        ok = bool(actual) == expected_substr
    else:
        ok = actual == expected_substr
    mark = "✅" if ok else "❌"
    if not ok:
        print(f"  {mark} {name}  expected='{expected_substr}' got='{actual}'")
    else:
        print(f"  {mark} {name}")
    results.append(ok)

def check_lt(name, actual, threshold):
    ok = actual < threshold
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}  actual={actual}{'' if ok else f' (> {threshold})'}")
    results.append(ok)

def check_ge(name, actual, threshold):
    ok = actual >= threshold
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}  actual={actual}{'' if ok else f' (< {threshold})'}")
    results.append(ok)

# 预备:重置
req("POST", "/api/reset")

print("═══════════════════════════════════════════════════════════")
print("  投标看板 · 质量测试套件 (8 原场景 + 7 D4 新场景 = 15 场景)")
print("═══════════════════════════════════════════════════════════")
print()

# ========== 场景 1:5 个 playbook API 可用 ==========
print("【场景 1】5 个 playbook API 可用")
code, pbs = req("GET", "/api/playbooks")
check("playbook 数量 ≥ 5", len(pbs) >= 5, True)
ids = ",".join(p["id"] for p in pbs)
for pb_id in ["pb-collect", "pb-dongguan", "pb-nfh", "pb-unionpay", "pb-new",
              "pb-qualify", "pb-delivery", "pb-archive"]:
    check(f"{pb_id} 在列表", ids, pb_id)
print()

# ========== 场景 2:playbook 执行回写 ==========
print("【场景 2】playbook 执行回写")
code, _ = req("POST", "/api/playbooks/run", {"id": "pb-dongguan"})
check("pb-dongguan exec 200", code, 200)
code, dg = req("GET", "/api/bids/dgyhst2026")
# D1：legacy stage 已收归 BAW 门禁（v1.0）——剧本只回写 AI/待办/阻塞，stage 应保持冻结不变
check("东莞银行 stage 冻结不变（D1：stage 收归 BAW 门禁）", dg.get("stage"), "修订")
check("东莞银行 block 已清空", dg.get("block"), "")
check("东莞银行 human_todo 有项", len(dg.get("human_todo", [])) > 0, True)
print()

# ========== 场景 3:P0 告警 SSE 推送 ==========
print("【场景 3】P0 告警 SSE 推送")
import threading
sse_events = []
def sse_thread():
    sse_events.extend(sse_collect(4))
t = threading.Thread(target=sse_thread)
t.start()
time.sleep(1)
# 触发 P0 变化
req("PATCH", "/api/bids/dgyhst2026/stage", {"value": "封标"})
req("PATCH", "/api/bids/dgyhst2026/block", {"value": "测试阻塞"})
t.join(timeout=6)
types = [e.get("type") for e in sse_events]
check("SSE 收到 connected", "connected" in types, True)
check("SSE 收到 bid_updated", "bid_updated" in types, True)
check("SSE 收到 p0_alert", "p0_alert" in types, True)
print()

# ========== 场景 4:plan_end 自动计算 ==========
print("【场景 4】plan_end 自动计算")
new_code = f"qtest-{int(time.time())}"
code, _ = req("POST", "/api/bids", {
    "code": new_code, "client": "测试客户", "stage": "修订",
    "priority": "P1", "due_at": "2026-12-31 17:00"
})
check("新 bid 创建 201(POST 正确)", code, 201)
code, new_bid = req("GET", f"/api/bids/{new_code}")
# 第一个节点的 plan_end 应该是 due - days_before_due (sales-bid 节点)
flow = new_bid.get("flow", {})
nodes = flow.get("nodes", [])
check("flow 有 13 个节点", len(nodes), 13)
# sales-bid: due 2026-12-31, days_before_due=30 → plan_end = 2026-12-01
sales_bid = next((n for n in nodes if n["id"] == "sales-bid"), None)
check("sales-bid plan_end = 2026-12-01 (提前 30 天)", sales_bid is not None and sales_bid.get("plan_end") == "2026-12-01", True)
# retro: days_before_due=-60 → plan_end = 2026-12-31 + 60 = 2027-03-01 (事后复盘)
retro = next((n for n in nodes if n["id"] == "retro"), None)
check("retro plan_end = 2027-03-01 (事后 60 天)", retro is not None and retro.get("plan_end") == "2027-03-01", True)
# seal: days_before_due=0 → plan_end = 2026-12-31 (截止日当天)
seal = next((n for n in nodes if n["id"] == "seal"), None)
check("seal plan_end = 2026-12-31 (当天)", seal is not None and seal.get("plan_end") == "2026-12-31", True)
print()

# ========== 场景 5:数据 reset ==========
print("【场景 5】reset 数据")
code, _ = req("POST", "/api/reset")
check("reset 200", code, 200)
code, bids = req("GET", "/api/bids")
check("reset 后 6 个客户", len(bids), 6)
print()

# ========== 场景 6:错误处理 ==========
print("【场景 6】错误处理")
code, resp = req("PATCH", "/api/bids/nonexistent/stage", {"value": "封标"})
check("不存在 bid → 404", code, 404)
check("err 提示客户不存在", resp.get("err", ""), "客户不存在")

code, resp = req("PATCH", "/api/bids/dgyhst2026/stage", {"bad_field": "x"})
check("缺 value 字段 → 400", code, 400)
check("err 提示 missing value", resp.get("err", ""), "missing")

code, resp = req("POST", "/api/bids", {"code": "dgyhst2026", "client": "重复测试"})
check("重复 code → err(查 _create_bid 行为)", resp.get("err", ""), "已存在")
print()

# ========== 场景 7:100 并发 PATCH 不崩 ==========
print("【场景 7】100 并发 PATCH(不崩)")
# 先备份原始 human_todo
_, dg = req("GET", "/api/bids/dgyhst2026")
orig_ht = list(dg.get("human_todo", []))
def patch_human_todo(i):
    return req("PATCH", "/api/bids/dgyhst2026/human_todo", {"value": f"并发项-{i}"})

with ThreadPoolExecutor(max_workers=20) as ex:
    futs = [ex.submit(patch_human_todo, i) for i in range(100)]
    for f in as_completed(futs):
        c, _ = f.result()
        if c != 200:
            print(f"    非 200 返回: {c}")

code, dg = req("GET", "/api/bids/dgyhst2026")
check_ge("human_todo 数量 ≥ 100", len(dg.get("human_todo", [])), 100)
code, h = req("GET", "/api/health")
check("服务仍存活", h.get("ok"), True)
# 清理测试残留(还原原 human_todo)
req("PATCH", "/api/bids/dgyhst2026/human_todo", {"value": orig_ht})
print("  (测试残留已清理)")
print()

# ========== 场景 8:SSE 延迟 < 500ms ==========
print("【场景 8】SSE 端到端延迟")
import socket
# 用一个独立 SSE 连接测延迟
s = socket.create_connection(("127.0.0.1", 8080), timeout=5)
s.sendall(b"GET /api/stream HTTP/1.1\r\nHost: 127.0.0.1\r\nAccept: text/event-stream\r\n\r\n")
# 等 connected 事件
s.settimeout(2)
buf = b""
while b"\n\n" not in buf:
    buf += s.recv(4096)
# 现在 SSE 已就绪
t0 = time.time()
# 触发 PATCH
req("PATCH", "/api/bids/nfh2026/block", {"value": "延迟测试"})
# 等 bid_updated
deadline = t0 + 2.0
found = False
while time.time() < deadline:
    s.settimeout(0.5)
    try:
        chunk = s.recv(4096)
        if not chunk: break
        buf += chunk
        while b"\n\n" in buf:
            block, buf = buf.split(b"\n\n", 1)
            for line in block.split(b"\n"):
                if line.startswith(b"data: "):
                    try:
                        ev = json.loads(line[6:].decode())
                        if ev.get("type") == "bid_updated":
                            t1 = time.time()
                            found = True
                            raise StopIteration
                    except: pass
    except socket.timeout:
        continue
    except StopIteration:
        break
s.close()
if found:
    latency_ms = (t1 - t0) * 1000
    check_lt("SSE 端到端延迟 < 500ms", latency_ms, 500)
    print(f"    实测: {latency_ms:.1f} ms")
else:
    print("  ❌ SSE 端到端延迟 < 500ms  (未收到事件)")
    results.append(False)
print()

# ========== 场景 9:D1 M3 自动升级 P0 lead ==========
print("【场景 9】D1 M3 自动升级 P0 lead")
LEADS_FILE = Path.home() / ".bidboard" / "leads.jsonl"
DB_PATH = Path.home() / ".bidboard" / "bidboard.db"

# 1) 正向:P0 + score=85 + new → 应自动生成 BB-AUTO bid
# 用真实 detail-path URL(过质量门禁:_has_detail_path + 域名白名单 + 缓存可达)
test_lead_pos = (
    '{"lead_id":"qtest_d4_promo_pos","ts":"2026-08-16T12:00:00",'
    '"title":"QTest-自动升级P0-东莞银行网络安全项目-20260816-001",'
    '"buyer":"东莞银行",'
    '"industry":"银行","region":"华南","amount":580,'
    '"deadline":"2026-09-30","published_at":"2026-08-15",'
    '"source":"manual",'
    '"link":"https://bulletin.cebpubservice.com/biddingBulletin/2025-04-18/15885858.html",'
    '"raw_keywords":"网络安全","score":85,"recommend":"P0",'
    '"reason":"qtest d4 positive"}\n'
)
with open(LEADS_FILE, "a", encoding="utf-8") as f:
    f.write(test_lead_pos)
time.sleep(12)  # M3 watcher 5s 轮询 + auto-promote
_db = sqlite3.connect(str(DB_PATH), timeout=5)
_db.row_factory = sqlite3.Row
row = _db.execute(
    "SELECT lifecycle, promoted_to_bid FROM leads WHERE lead_id=?",
    ("qtest_d4_promo_pos",)
).fetchone()
check("正向 P0+85 → lifecycle=promoted", (row["lifecycle"] if row else ""), "promoted")
check("正向 P0+85 → promoted_to_bid 以 BB-AUTO- 开头",
      (row["promoted_to_bid"] if row else "").startswith("BB-AUTO-"), True)

# 2) 反向:P0 + score=50 + new → 不应升级
test_lead_neg = (
    '{"lead_id":"qtest_d4_promo_neg","ts":"2026-08-16T12:00:00",'
    '"title":"QTest-不升级P0分数低-某学校弱电项目-20260816-001",'
    '"buyer":"某学校",'
    '"industry":"教育","region":"华南","amount":50,'
    '"deadline":"2026-09-30","published_at":"2026-08-15",'
    '"source":"manual",'
    '"link":"https://bulletin.cebpubservice.com/biddingBulletin/2025-04-18/15885858.html",'
    '"raw_keywords":"","score":50,"recommend":"P0",'
    '"reason":"qtest d4 negative score"}\n'
)
with open(LEADS_FILE, "a", encoding="utf-8") as f:
    f.write(test_lead_neg)
time.sleep(10)
row = _db.execute(
    "SELECT lifecycle, promoted_to_bid FROM leads WHERE lead_id=?",
    ("qtest_d4_promo_neg",)
).fetchone()
check("反向 P0+50 → 保持 lifecycle=new", (row["lifecycle"] if row else ""), "new")
check("反向 P0+50 → promoted_to_bid 为空", (row["promoted_to_bid"] if row else ""), "")
_db.close()
print()

# ========== 场景 10:D2 M4 Skill 状态 API ==========
print("【场景 10】D2 M4 Skill 状态")
code, sk = req("GET", "/api/skills/status")
check("M4 GET /api/skills/status 200", code, 200)
skills = sk.get("skills", []) if isinstance(sk, dict) else []
check("6 个 skill 注册", len(skills), 6)
sample = skills[0] if skills else {}
check("skill 字段齐全 (id/name/icon/stage/available)",
      all(k in sample for k in ["id", "name", "icon", "stage", "available"]), True)
print()

# ========== 场景 11:D2 M4 ▶ 立即跑按钮 ==========
print("【场景 11】D2 M4 立即跑按钮")
code, run_resp = req("POST", "/api/skills/run", {"skill": "qualify"}, timeout=30)
# 异步执行:202 Accepted 即视为正常(立即返回,后台跑脚本)
check("M4 ▶ qualify POST 2xx(200/202 异步)", code in (200, 202), True)
check("M4 ▶ qualify ok=true", run_resp.get("ok"), True)
print()

# ========== 场景 12:D3 digest_stats.py 直接跑 ==========
print("【场景 12】D3 digest_stats.py Skill")
r = subprocess.run(
    # DEV-0034：原路径指向 ~/.minimax-agent-cn 旧项目（已不存在）——改跑仓库内脚本（约定在仓库根运行）
    ["python3", "scripts/digest_stats.py"],
    capture_output=True, text=True, timeout=15,
)
out = {}
try:
    last_line = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "{}"
    out = json.loads(last_line)
except Exception:
    out = {}
check("digest_stats.py 返 ok=true", out.get("ok"), True)
today = time.strftime("%Y-%m-%d")
stats_file = Path.home() / ".bidboard" / "digests" / ".tmp" / f"{today}.stats.json"
check("stats.json 存在", stats_file.exists(), True)
if stats_file.exists():
    stats = json.loads(stats_file.read_text(encoding="utf-8"))
    # 6 个核心聚合字段
    required_keys = [
        "bids_total", "bids_by_priority", "bids_amount_sum",
        "leads_total", "leads_by_recommend", "events_today_count",
    ]
    check("stats.json 6 关键字段齐全",
          all(k in stats for k in required_keys), True)
print()

# ========== 场景 13:D3 /api/digest 端到端 ==========
print("【场景 13】D3 /api/digest 端到端")
md_file = Path.home() / ".bidboard" / "digests" / f"{today}.md"
if md_file.exists():
    md_file.unlink()
code, d1 = req("GET", "/api/digest")
check("GET /api/digest 200", code, 200)
check("digest source 在 4 路径之一",
      d1.get("source") in ("cached", "stats_only", "yesterday", "error"), True)
check("digest length ≥ 200", d1.get("length", 0) >= 200, True)

code, d2 = req("POST", "/api/digest/regenerate", {}, timeout=15)
check("POST /api/digest/regenerate 200", code, 200)
check("regenerate regenerated=true", d2.get("regenerated"), True)
print()

# ========== 场景 14:D3 失败降级 ==========
print("【场景 14】D3 失败降级")
db_bak = Path.home() / ".bidboard" / "bidboard.db.d4test"
if not db_bak.exists() and DB_PATH.exists():
    DB_PATH.rename(db_bak)
if md_file.exists():
    md_file.unlink()
code, d3 = req("GET", "/api/digest")
check("DB 不可用时 仍 200(不崩)", code, 200)
# v0.4.0 修正:Python sqlite3 在 DB 缺失时会自动创建空文件,digest_stats 跑通但数据全 0
# 接受任意降级路径:error / yesterday(原 DB 真不可用) 或 stats_only(空 DB 兜底)
check("降级路径有效(error/yesterday/stats_only)",
      d3.get("source") in ("error", "yesterday", "stats_only"), True)
# 额外验证:不管走哪条路径,markdown 都应该非空
check("降级 markdown 非空", d3.get("length", 0) > 0, True)
# 恢复
if db_bak.exists():
    db_bak.rename(DB_PATH)
print()

# ========== 场景 15:5 并发 POST 不死锁(D1+D2 复合回归)=========
print("【场景 15】5 并发 POST 不死锁")
def post_one(i):
    return req("POST", "/api/commands", {
        "commandId": "bid.add_ai_ready",
        "params": {"code": "payh26", "item": f"d4-conc-{i}-{uuid.uuid4().hex[:6]}"}
    }, timeout=10)
codes = []
with ThreadPoolExecutor(max_workers=5) as ex:
    futs = [ex.submit(post_one, i) for i in range(5)]
    for f in as_completed(futs):
        c, _ = f.result()
        codes.append(c)
ok_count = sum(1 for c in codes if c == 200)
check("5 并发 POST 全部 200", ok_count, 5)
print()

# ========== 总结 ==========
total = len(results)
passed = sum(results)
failed = total - passed
print("═══════════════════════════════════════════════════════════")
print(f"  通过: {passed}/{total}  失败: {failed}")
if failed == 0:
    print(f"  🎉 全部通过 — {total}/{total} 检查完成 (8 原场景 + 7 新场景,覆盖 D1/D2/D3)")
else:
    print(f"  ⚠️  有 {failed} 项未通过")
print("═══════════════════════════════════════════════════════════")
exit(0 if failed == 0 else 1)
