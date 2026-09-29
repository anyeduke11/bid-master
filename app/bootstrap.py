#!/usr/bin/env python3
"""app/bootstrap.py · 显式启动序列（收编原 server.py import 副作用，DEV-0042）

顺序：建目录 → app.db init → truth.db init → 事件恢复 → 自愈清理 →
自动归档检查 → 时效扫描 → demo 播种（空库且非 BIDBOARD_EMPTY）→ 后台线程。
"""
import sys

from . import config
from .store import app_db
from .services import bid_service, lead_store, notify


def seed_demo_bids():
    """6 个 demo 标（自 server.py _initial_data + _DEFAULT_BUSINESS_FIELDS 迁移）。
    kind=demo 写真实层（store 按 DEMO_MARKERS 兜底判定；这些 code 无标记，显式 kind=demo）。"""
    import store as truth
    import datetime as _dt
    today_last_sync = _dt.date.today().strftime("%Y-%m-%d") + " 09:30:00"

    def _flow(blocked, nodes):
        return {"blocked_node": blocked, "nodes": nodes}

    demo = [
        {"code": "dgyhst2026", "client": "东莞银行", "stage": "修订", "priority": "P0",
         "due_at": "2026-08-13 17:00", "ai_ready": ["JSON 校验", "格式检查"],
         "human_todo": ["报价签字", "述标要点过"], "block": "", "last_sync": today_last_sync,
         "tier": "大B", "industry": "银行", "region": "华南", "est_amount": 280,
         "decision_maker": "张行长", "competitors": ["绿盟", "启明"],
         "flow": _flow("quote", [
             {"id": "sales-bid", "status": "done", "actual_end": "2026-07-15"},
             {"id": "buy-rfp", "status": "done", "actual_end": "2026-07-30"},
             {"id": "quote", "status": "blocked", "block_reason": "报价签字待终签"},
             {"id": "case", "status": "done", "actual_end": "2026-08-05"},
             {"id": "qualification", "status": "done", "actual_end": "2026-08-06"},
             {"id": "tech-solution", "status": "done", "actual_end": "2026-08-08"},
             {"id": "biz-solution", "status": "done", "actual_end": "2026-08-09"},
             {"id": "draft", "status": "done", "actual_end": "2026-08-10"},
             {"id": "final", "status": "progress"},
             {"id": "seal", "status": "pending"},
             {"id": "present", "status": "pending"},
             {"id": "notice", "status": "pending"},
             {"id": "retro", "status": "pending"}])},
        {"code": "nfh2026", "client": "农发行", "stage": "修订", "priority": "P1",
         "due_at": "2026-08-16 18:00", "ai_ready": ["差异点比对"],
         "human_todo": ["技术方案重写"], "block": "", "last_sync": today_last_sync,
         "tier": "大B", "industry": "银行", "region": "华北", "est_amount": 450,
         "decision_maker": "李主任", "competitors": ["深信服"],
         "flow": _flow(None, [
             {"id": "sales-bid", "status": "done", "actual_end": "2026-06-10"},
             {"id": "buy-rfp", "status": "done", "actual_end": "2026-07-20"},
             {"id": "quote", "status": "done", "actual_end": "2026-07-25"},
             {"id": "case", "status": "done", "actual_end": "2026-08-01"},
             {"id": "qualification", "status": "done", "actual_end": "2026-08-02"},
             {"id": "tech-solution", "status": "progress"},
             {"id": "biz-solution", "status": "progress"},
             {"id": "draft", "status": "pending"},
             {"id": "final", "status": "pending"},
             {"id": "seal", "status": "pending"},
             {"id": "present", "status": "pending"},
             {"id": "notice", "status": "pending"},
             {"id": "retro", "status": "pending"}])},
        {"code": "unionpay-intl26-1", "client": "银联国际 #1", "stage": "审查", "priority": "P2",
         "due_at": "2026-08-20 17:00", "ai_ready": ["检查表就绪"], "human_todo": [], "block": "",
         "last_sync": today_last_sync, "tier": "大B", "industry": "金融", "region": "华东",
         "est_amount": 800, "decision_maker": "王总监", "competitors": ["亚信", "某网络安全服务商"],
         "flow": _flow(None, [{"id": n, "status": ("done" if i < 1 else ("progress" if i == 1 else "pending"))}
                              for i, n in enumerate(_NODE_NAMES)])},
        {"code": "unionpay-intl26-2", "client": "银联国际 #2", "stage": "审查", "priority": "P2",
         "due_at": "2026-08-20 17:00", "ai_ready": ["检查表就绪"], "human_todo": [], "block": "分包边界未明",
         "last_sync": today_last_sync, "tier": "大B", "industry": "金融", "region": "华东",
         "est_amount": 750, "decision_maker": "王总监", "competitors": ["亚信"],
         "flow": _flow("quote", [{"id": n, "status": ("done" if i < 1 else ("blocked" if i == 2 else "pending"))}
                                 for i, n in enumerate(_NODE_NAMES)])},
        {"code": "unionpay-intl26-3", "client": "银联国际 #3", "stage": "审查", "priority": "P2",
         "due_at": "2026-08-20 17:00", "ai_ready": [], "human_todo": [], "block": "",
         "last_sync": today_last_sync, "tier": "大B", "industry": "金融", "region": "华东",
         "est_amount": 900, "decision_maker": "王总监", "competitors": ["某网络安全服务商"],
         "flow": _flow(None, [{"id": n, "status": ("done" if i < 1 else ("progress" if i == 1 else "pending"))}
                              for i, n in enumerate(_NODE_NAMES)])},
        {"code": "payh26", "client": "平安银行", "stage": "跟踪", "priority": "P2",
         "due_at": "持续", "ai_ready": ["标讯监控中"], "human_todo": [], "block": "",
         "last_sync": today_last_sync, "tier": "大B", "industry": "银行", "region": "华南",
         "est_amount": 350, "decision_maker": "陈行长", "competitors": [],
         "flow": _flow(None, [{"id": n, "status": "pending"} for n in _NODE_NAMES])},
    ]
    for b in demo:
        code = b.pop("code")
        kind = "demo" if any(m in code.lower() for m in truth.DEMO_MARKERS) else "demo"  # 播种一律 demo
        try:
            truth.create_bid(code, "S0", bootstrapped=True, note="demo 播种（重置可清）", kind="demo")
        except Exception:
            pass  # 已存在（幂等重播）
        bid_service._enrich(b, status="active")
        truth.upsert_bid_profile(code, b)


_NODE_NAMES = ["sales-bid", "buy-rfp", "quote", "case", "qualification", "tech-solution",
               "biz-solution", "draft", "final", "seal", "present", "notice", "retro"]


def bootstrap(start_watchers: bool = True) -> None:
    """显式启动（替代原 import 副作用）。create_server/main 调用。"""
    config.ensure_dirs()
    app_db.init()

    import store as truth
    truth.init()

    # 事件恢复（跨重启可查）
    notify.load_events_into_memory(200)

    # boot 自愈：软过期 lead 定向删除（> 2 * FRESH_DAYS）
    try:
        lead_store.purge_stale_leads()
    except Exception as e:
        print(f"[init] 自愈检查失败: {e}", file=sys.stderr)

    # 自动归档检查
    try:
        bid_service.auto_archive_check()
    except Exception as e:
        print(f"[init] auto_archive_check failed: {e}", file=sys.stderr)

    # 时效扫描（aging/expired 标记）
    try:
        result = lead_store.scan_lead_freshness()
        print(f"[init] 📦 lead 时效扫描: 扫描 {result['scanned']} 条 · 关闭区 {len(result['expired'])} 条 · 老化 {len(result['aging'])} 条 · 跳已 promote {result.get('skip', 0)} 条", file=sys.stderr)
    except Exception as e:
        print(f"[init] lead 时效扫描失败: {e}", file=sys.stderr)

    # demo 播种（空库且非空板开关）
    if not config.BIDBOARD_EMPTY and not truth.load_bids() and not truth.list_bid_profiles():
        seed_demo_bids()
        print("[init] 播种 6 个 demo 标（BIDBOARD_EMPTY=1 可关闭）", file=sys.stderr)
    elif config.BIDBOARD_EMPTY:
        print("[boot] BIDBOARD_EMPTY=1 · 空板启动（无演示客户/事件）", file=sys.stderr)

    if start_watchers:
        from .services import watchers
        watchers.start_file_watcher()
        watchers.start_freshness_scanner()
        # DEV-0081：服务内置周期调度（3h 一轮，替代 crontab/launchd——调度随服务生死）
        from .services import scheduler
        scheduler.start_scheduler()
