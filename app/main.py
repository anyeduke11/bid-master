#!/usr/bin/env python3
"""app/main.py · 服务装配（create_server / main；server.py 瘦身为本文件的打印包装）"""
import argparse
import threading
from http.server import ThreadingHTTPServer

from . import config
from .bootstrap import bootstrap
from .web.router import Router
from .web.http import AppHandler, SSEHub
from .services import command_engine, bid_commands, lead_commands, gate_commands
from .api import meta, bids, leads, commands, baw, agents, skills, system, capture, kb

API = "/api/v1"

# ── 路由注册表（域 → 路由列表） ──
# 每条 = (method, path_template, handler, 一句话描述)
_ROUTES = [
    # ── meta 域：健康/初始化/统计/日志/摘要 ──
    ("GET",    f"{API}/health",          meta.health,        "健康检查"),
    ("GET",    f"{API}/initial",         meta.initial,        "首屏初始化聚合"),
    ("GET",    f"{API}/stats",           meta.stats,          "看板统计"),
    ("GET",    f"{API}/bids/summary",    meta.bids_summary,   "标汇总"),
    ("GET",    f"{API}/logs",            meta.logs,            "事件日志流"),
    ("GET",    f"{API}/digest",          meta.digest,          "digest 日报"),
    ("GET",    f"{API}/summary",         meta.summary,         "汇总报告"),
    # ── bids 域：标列表/详情（超集形状） ──
    ("GET",    f"{API}/bids",            bids.list_bids,      "标列表（BAW+看板超集）"),
    ("GET",    f"{API}/bids/{{code}}",   bids.get_bid,         "标详情（超集形状）"),
    ("GET",    f"{API}/bids/{{bid_id}}/deep", bids.deep_dive,  "单标深潜详情"),
    # ── leads 域：商机线索 ──
    ("GET",    f"{API}/leads/closed",    leads.closed_leads,  "已关闭线索"),
    ("GET",    f"{API}/leads",           leads.list_leads,     "线索列表（多维排序）"),
    ("POST",   f"{API}/leads/scan-freshness", leads.scan_freshness, "时效扫描"),
    # ── commands 域：写唯一通道（幂等+审计） ──
    ("POST",   f"{API}/commands",        commands.post_command, "命令网关（所有写操作）"),
    ("GET",    f"{API}/commands",        commands.list_commands, "命令注册表+schema"),
    ("GET",    f"{API}/commands/list",   commands.list_commands, "命令注册表（别名）"),
    ("GET",    f"{API}/commands/{{exec_id}}", commands.get_execution, "执行结果查询"),
    # ── baw 域：BAW 观测层（只读 truth.db） ──
    ("GET",    f"{API}/baw/bids",        baw.bids,             "BAW live bids"),
    ("GET",    f"{API}/baw/epoch",       baw.epoch,            "epoch 时钟（别名）"),
    ("GET",    f"{API}/baw/alerts",      baw.alerts,           "告警（别名）"),
    ("GET",    f"{API}/epoch",           baw.epoch,            "epoch 时钟"),
    ("GET",    f"{API}/alerts",          baw.alerts,           "告警列表"),
    ("GET",    f"{API}/views/{{name}}",  baw.view,             "管线视图 now/funnel/system"),
    ("GET",    f"{API}/views/bid/{{bid_id}}", baw.view_bid,   "标深潜视图"),
    ("GET",    f"{API}/bids/{{bid_id}}/gate", baw.gate_query,  "门禁阻塞项查询"),
    # ── capture 域：标讯抓取/inbox ──
    ("GET",    f"{API}/inbox/status",    capture.inbox_status, "inbox/capture 状态"),
    ("POST",   f"{API}/capture/run",     capture.run_capture,  "手动触发标讯抓取"),
    # ── kb 域：资产台账（DEV-0081：补齐前端 07 视图的缺失路由） ──
    ("GET",    f"{API}/kb/cert",         kb.cert,              "资产台账 · 证照"),
    ("GET",    f"{API}/kb/people",       kb.people,            "资产台账 · 人员"),
    ("GET",    f"{API}/kb/case",         kb.case,              "资产台账 · 案例"),
    ("GET",    f"{API}/kb/solution",     kb.solution,          "资产台账 · 方案"),
    ("GET",    f"{API}/kb/alerts",       kb.alerts,            "资产台账 · 预警"),
    # ── agents 域：智能体五接触面 ──
    ("GET",    f"{API}/tickets",         agents.tickets,      "工单列表"),
    ("GET",    f"{API}/contracts/agents", agents.contracts_agents, "智能体契约"),
    ("GET",    f"{API}/contracts/artifacts", agents.contracts_artifacts, "产物契约"),
    ("GET",    f"{API}/lessons",         agents.lessons,       "教训库（只读）"),
    ("GET",    f"{API}/spec-template",   agents.spec_template, "规格模板"),
    ("GET",    f"{API}/agent/queue",     agents.queue,         "agent 请求队列"),
    ("POST",   f"{API}/agent/ask",       agents.ask,           "向 Mavis 排队问答"),
    ("POST",   f"{API}/agent/answer",    agents.answer,        "Mavis 写回回答"),
    # ── skills 域：技能/剧本编排 ──
    ("GET",    f"{API}/skills/status",   skills.status,        "技能状态"),
    ("POST",   f"{API}/skills/run",      skills.run,           "异步执行技能（透传 bid_id）"),
    ("GET",    f"{API}/skills/runs",      skills.list_runs,     "执行记录列表"),
    ("GET",    f"{API}/skills/runs/{{run_id}}", skills.get_run, "执行记录详情"),
    ("GET",    f"{API}/playbooks",       skills.playbooks_list, "剧本列表"),
    ("POST",   f"{API}/playbooks/run",   skills.playbooks_run,  "执行剧本（透传 bid_id）"),
    ("GET",    f"{API}/activity",        skills.activity,       "统一活动日志"),
    ("POST",   f"{API}/next-actions/sync", skills.next_actions_sync, "zcode 智能建议同步（快照替换）"),
    ("GET",    f"{API}/next-actions",    skills.next_actions_list, "当前智能建议快照"),
    # ── system 域：运维操作 ──
    ("POST",   f"{API}/digest/regenerate", system.digest_regenerate, "digest 重算"),
    ("GET",    f"{API}/scheduler",         system.scheduler_status, "内置调度器状态（3h 一轮）"),
    ("POST",   f"{API}/scheduler/run",     system.scheduler_run,   "手动触发一轮调度"),
    ("POST",   f"{API}/reset",           system.reset,         "重置为 demo 数据"),
    ("POST",   f"{API}/debug/beacon",    system.beacon,        "客户端诊断信标（写本地日志，不入库）"),
]

# ── 域分组（用于 banner + /routes 端点） ──
_DOMAINS = [
    ("meta",     "健康/初始化/统计/日志/摘要"),
    ("bids",     "标列表/详情（超集形状）"),
    ("leads",    "商机线索"),
    ("commands", "命令网关（写唯一通道）"),
    ("baw",      "BAW 观测层（只读）"),
    ("kb",       "资产台账（kb_assets 只读）"),
    ("agents",   "智能体五接触面"),
    ("skills",   "技能/剧本编排"),
    ("system",   "系统运维"),
]

# 路由前缀 → 域名映射
_PREFIX_DOMAIN = {
    "/health": "meta", "/initial": "meta", "/stats": "meta",
    "/bids/summary": "meta", "/logs": "meta", "/digest": "meta", "/summary": "meta",
    "/bids": "bids",
    "/leads": "leads",
    "/commands": "commands",
    "/baw": "baw", "/epoch": "baw", "/alerts": "baw", "/views": "baw",
    "/tickets": "agents", "/contracts": "agents", "/lessons": "agents",
    "/spec-template": "agents", "/agent": "agents",
    "/skills": "skills", "/playbooks": "skills",
    "/reset": "system", "/digest/regenerate": "system",
    "/routes": "meta",
}


def _domain_of(handler) -> str:
    """从 handler 所属模块推断域——比路径前缀更准确。"""
    mod = handler.__module__.replace("app.", "")
    # api.baw → baw, api.agents → agents, etc.
    if mod.startswith("api."):
        d = mod.replace("api.", "")
        if d in dict(_DOMAINS):
            return d
    return "other"


def build_router() -> Router:
    r = Router()
    for method, path, handler, _desc in _ROUTES:
        if method == "GET":
            r.get(path, handler)
        elif method == "POST":
            r.post(path, handler)
    # ── routes 发现端点 ──
    r.get(f"{API}/routes", routes_discovery)
    return r


def routes_discovery(req):
    """GET /api/v1/routes — 返回路由表（域分组），供智能体/前端自动发现 API 面。"""
    by_domain = {}
    for method, path, handler, desc in _ROUTES:
        domain = _domain_of(handler)
        by_domain.setdefault(domain, []).append({
            "method": method,
            "path": path,
            "handler": f"{handler.__module__.replace('app.', '')}.{handler.__name__}",
            "desc": desc,
        })
    domains = [{"domain": d, "desc": desc, "routes": by_domain.get(d, [])}
               for d, desc in _DOMAINS if d in by_domain]
    return 200, {"ok": True, "total": len(_ROUTES), "domains": domains}


def register_all_commands():
    command_engine.COMMAND_REGISTRY.clear()
    bid_commands.register_all()
    lead_commands.register_all()
    gate_commands.register_all()


def _print_banner(host: str, port: int):
    """启动 banner：域分布 + 路由表一目了然。"""
    # 按域统计路由数
    domain_counts = {}
    for method, path, handler, desc in _ROUTES:
        d = _domain_of(handler)
        domain_counts[d] = domain_counts.get(d, 0) + 1

    W = 62
    lines = []
    lines.append("")
    lines.append("  ╔" + "═" * W + "╗")
    title = f"bid-master 统一服务 · v1 API（{len(domain_counts)} 域 {len(_ROUTES)} 路由）"
    lines.append("  ║" + title.center(W) + "║")
    lines.append("  ╠" + "═" * W + "╣")
    lines.append(f"  ║  看板:    http://{host}:{port}/".ljust(W + 4)[:W + 4] + "║")
    lines.append(f"  ║  路由表:  http://{host}:{port}/api/v1/routes".ljust(W + 4)[:W + 4] + "║")
    lines.append(f"  ║  健康:    http://{host}:{port}/api/v1/health".ljust(W + 4)[:W + 4] + "║")
    lines.append(f"  ║  M3 监听: ~/.bidmaster/leads/*.jsonl (5s 轮询)".ljust(W + 4)[:W + 4] + "║")
    lines.append(f"  ║  调度器:  内置 3h 一轮（GET /api/v1/scheduler；随服务启停）".ljust(W + 4)[:W + 4] + "║")
    lines.append(f"  ║  写操作:  POST /api/v1/commands（幂等+审计+X-Agent-Id）".ljust(W + 4)[:W + 4] + "║")
    lines.append(f"  ║  数据:    truth.db + app.db（~/.bidmaster）".ljust(W + 4)[:W + 4] + "║")
    lines.append("  ╠" + "─" * W + "╣")
    for domain, desc in _DOMAINS:
        if domain in domain_counts:
            line = f"  {domain:10s} {domain_counts[domain]:2d} 路由   {desc}"
            lines.append(line.ljust(W + 4)[:W + 4] + "║")
    lines.append("  ╠" + "─" * W + "╣")
    lines.append(f"  ║  按 Ctrl+C 停止".ljust(W + 4)[:W + 4] + "║")
    lines.append("  ╚" + "═" * W + "╝")
    lines.append("")
    print("\n".join(lines), flush=True)


def create_server(host="127.0.0.1", port=0, start_watchers=True):
    """装配并返回已 boot 的 ThreadingHTTPServer（port=0 随机端口，测试用）。"""
    bootstrap(start_watchers=start_watchers)
    register_all_commands()
    AppHandler.router = build_router()
    AppHandler.sse = SSEHub()
    AppHandler.public_dir = config.PUBLIC_DIR
    AppHandler.repo_dir = config.REPO
    return ThreadingHTTPServer((host, port), AppHandler)


def main():
    ap = argparse.ArgumentParser(description="bid-master 统一服务（v1 API）")
    ap.add_argument("--port", type=int, default=config.PORT)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    srv = create_server(args.host, args.port, start_watchers=True)
    port = srv.server_address[1]
    _print_banner(args.host, port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 停止", file=__import__("sys").stderr)
        srv.shutdown()


if __name__ == "__main__":
    main()
