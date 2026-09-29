#!/usr/bin/env python3
"""app/services/digest_service.py · M6 日报（自 server.py 2371-2529 迁移）

stats 直接进程内计算（原 subprocess 跑 scripts/digest_stats.py 读旧库—— retired），
聚合口径与 digest_stats.py 一致（bids/leads/events 全维度），Mavis 排队语义保留。
"""
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from .. import config
from . import bid_service, notify
from ..store import app_db


def compute_stats(target_date: str, exclude_classified: bool = False) -> dict:
    """当日统计（聚合键与原 digest_stats.py 输出对齐）。
    R5（工程审查 2026-09-19）：exclude_classified=True 供云队列 payload 用——涉密壳从全部
    聚合剔除（防行业/区域/金额/阶段反推），classified_count 标量保留（只知有几单，不知细节）。
    本地渲染与 stats.json 落盘走默认全量。"""
    bids = bid_service.all_bids("all")
    n_classified = sum(1 for b in bids if b.get("kind") == "classified")
    if exclude_classified:
        bids = [b for b in bids if b.get("kind") != "classified"]
    leads = app_db.load_leads(limit=10000)
    pri = {"P0": 0, "P1": 0, "P2": 0}
    by_stage, by_industry, by_region = {}, {}, {}
    amount_sum = 0
    for b in bids:
        pri[b.get("priority", "P2")] = pri.get(b.get("priority", "P2"), 0) + 1
        by_stage[b.get("stage", "?")] = by_stage.get(b.get("stage", "?"), 0) + 1
        by_industry[b.get("industry") or "未分类"] = by_industry.get(b.get("industry") or "未分类", 0) + 1
        by_region[b.get("region") or "未分类"] = by_region.get(b.get("region") or "未分类", 0) + 1
        try:
            amount_sum += float(b.get("est_amount", 0) or 0)
        except (TypeError, ValueError):
            pass
    rec = {}
    p0_pending = []
    for l in leads:
        r = l.get("recommend") or ""
        rec[r] = rec.get(r, 0) + 1
        if r == "P0" and (l.get("lifecycle") or "new") not in ("promoted", "discarded"):
            p0_pending.append({"title": l.get("title", ""), "buyer": l.get("buyer", ""), "score": l.get("score", 0)})
    today_prefix = target_date
    events_today = [e for e in app_db.load_events(limit=2000) if (e.get("ts") or "").startswith(today_prefix)]
    return {
        "date": target_date,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "bids_total": len(bids),
        "bids_by_priority": pri,
        "bids_by_stage": by_stage,
        "bids_by_industry": by_industry,
        "bids_by_region": by_region,
        "bids_amount_sum": amount_sum,
        "classified_count": n_classified,
        "leads_total": len(leads),
        "leads_by_recommend": rec,
        "leads_p0_pending": p0_pending,
        "events_today_count": len(events_today),
    }


def _sanitize_cloud_stats(stats: dict) -> dict:
    """R5：Mavis 云队列 payload 终检（纯函数，单测友好）。
    存量 L3 修复：leads_p0_pending 含 buyer 名单+标题（L3 红线"客户名单不进任何 prompt"）
    → 整组剔除，只留 leads_p0_pending_count 计数。classified 聚合剔除在 compute_stats 完成。"""
    cloud = dict(stats)
    pending = cloud.pop("leads_p0_pending", None) or []
    cloud["leads_p0_pending_count"] = len(pending)
    return cloud


def _render(stats, ai_text=None):
    """从 stats + 可选 ai_text 渲染 markdown digest（与原实现同构）。"""
    lines = []
    lines.append(f"# 📅 今日投标摘要 · {stats.get('date', '')}")
    lines.append("")
    lines.append(f"_生成于: {stats.get('generated_at', '')}_")
    lines.append("")
    if ai_text:
        lines.append("## 🤖 Mavis 摘要")
        lines.append("")
        lines.append(ai_text)
        lines.append("")
    pri = stats.get("bids_by_priority", {})
    rec = stats.get("leads_by_recommend", {})
    p0_pend = stats.get("leads_p0_pending", [])
    amt = stats.get("bids_amount_sum", 0) or 0
    lines.append("## 📊 业务数据")
    lines.append("")
    lines.append(f"- **客户 bids**: {stats.get('bids_total', 0)} 个 "
                 f"(P0={pri.get('P0', 0)} / P1={pri.get('P1', 0)} / P2={pri.get('P2', 0)})")
    lines.append(f"- **商机 leads**: {stats.get('leads_total', 0)} 条 "
                 f"(P0={rec.get('P0', 0)} 待升级 {len(p0_pend)} / 跳过={rec.get('跳过', 0)})")
    lines.append(f"- **今日事件**: {stats.get('events_today_count', 0)} 条")
    lines.append(f"- **预估总金额**: {amt:.0f} 万")
    lines.append("")
    if p0_pend:
        lines.append("## 🎯 待升级 P0 lead")
        lines.append("")
        for p in p0_pend[:5]:
            lines.append(f"- **{p.get('title', '')}** ({p.get('buyer', '')}) score={p.get('score', 0)}")
        lines.append("")
    for icon, key, limit_ in (("⇉", "bids_by_stage", None), ("🏢", "bids_by_industry", 5), ("🌍", "bids_by_region", 5)):
        dist = stats.get(key) or {}
        if dist:
            title = {"⇉": "Stage 分布", "🏢": "行业分布", "🌍": "区域分布"}[icon]
            lines.append(f"## {icon} {title}")
            lines.append("")
            items = sorted(dist.items(), key=lambda x: -x[1])
            for k, v in items[:limit_ or len(items)]:
                lines.append(f"- {k}: {v}")
            lines.append("")
    return "\n".join(lines)


def get_or_generate(target_date=None, force=False):
    """获取/生成指定日期 digest。返回 (markdown, source, status)。
    source ∈ {'cached','stats_only','yesterday','error'}；status ∈ {'ok','degraded','error'}"""
    target_date = target_date or date.today().strftime("%Y-%m-%d")
    digest_file = config.DIGEST_DIR / f"{target_date}.md"
    config.ensure_dirs()

    if digest_file.exists() and not force:
        try:
            return digest_file.read_text(encoding="utf-8"), "cached", "ok"
        except Exception:
            pass

    try:
        stats = compute_stats(target_date)
        stats_file = config.DIGEST_TMP / f"{target_date}.stats.json"
        stats_file.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        notify.log_module("digest", f"stats 计算失败: {e}", "warn")
        try:
            yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
            yf = config.DIGEST_DIR / f"{yesterday}.md"
            if yf.exists():
                return (yf.read_text(encoding="utf-8") + f"\n\n_⚠️ 今日 stats 暂不可用,展示 {yesterday} digest_",
                        "yesterday", "degraded")
        except Exception:
            pass
        return ("# 今日数据暂无\n\n_app.db 暂不可读,建议稍后重试_", "error", "error")

    # 排队给 Mavis Agent（可选消费 stats → 写 .md 升级为 cached）
    # DEV-0052：Mavis 消费方缺位时队列文件只增不减（实测 6 个空转堆叠）——
    #   ① 同日 30 分钟窗口内不重复排队；② 清理 >7 天的陈旧队列文件；③ 滞留 >24h 记 warn 告警
    try:
        queue_dir = config.AGENT_QUEUE_DIR
        queue_dir.mkdir(parents=True, exist_ok=True)
        safe_date = "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in str(target_date))[:32]
        now_ts = time.time()
        existing = sorted(queue_dir.glob(f"digest_{safe_date}_*.json"))
        if existing:
            newest_age_min = (now_ts - existing[-1].stat().st_mtime) / 60
            stale = [f for f in queue_dir.glob("digest_*.json") if now_ts - f.stat().st_mtime > 7 * 86400]
            for f in stale:
                f.unlink()
            if newest_age_min < 30:
                # 同日 30 分钟窗口内已排过队且未被消费——跳过，防止每次刷新都堆一个文件
                notify.log_module("digest", "Mavis 队列 30 分钟窗口内已有同日任务，跳过重复排队", "info")
                raise _QueueThrottled()
            if newest_age_min > 24 * 60:
                # 滞留超一天仍未消费——如实告警（消费方缺位信号），仍补排一个新任务
                notify.log_module("digest", f"Mavis digest 队列滞留 {newest_age_min/60:.0f}h 未消费（消费方缺位？）", "warn")
        req_id = f"digest_{safe_date}_{int(time.time())}"
        req_file = queue_dir / f"{req_id}.json"
        # R5：云 payload 走脱敏链——壳聚合剔除（exclude_classified）+ leads buyer/title 剔除（终检）
        # 本地 stats_file 与 markdown 渲染保持全量（compute_stats 默认），仅出网内容受限。
        cloud_stats = _sanitize_cloud_stats(compute_stats(target_date, exclude_classified=True))
        req_data = {
            "id": req_id, "ts": datetime.now().isoformat(),
            "code": f"__digest_{target_date}", "client": "today_digest", "type": "digest",
            "question": (f"基于以下 stats 生成 {target_date} 投标看板今日 markdown 摘要(快读 3 条 + 详读全部):\n"
                         f"{json.dumps(cloud_stats, ensure_ascii=False, default=str)[:3000]}"),
            "context": cloud_stats, "target_date": target_date,
            "stats_file": str(config.DIGEST_TMP / f"{target_date}.stats.json"),
            "digest_file": str(digest_file),
        }
        req_file.write_text(json.dumps(req_data, ensure_ascii=False, indent=2), encoding="utf-8")
        notify.log_module("digest", f"🤖 Mavis digest 任务已排队(脱敏 payload): {req_id}", "info")
    except _QueueThrottled:
        pass
    except Exception as e:
        notify.log_module("digest", f"Agent 排队失败: {e}", "warn")

    markdown = _render(stats, ai_text=None)
    return markdown, "stats_only", "ok"


class _QueueThrottled(Exception):
    """同日排队节流命中——静默跳过本次排队（内部控制流）。"""


def regenerate(target_date=None):
    target_date = target_date or date.today().strftime("%Y-%m-%d")
    digest_file = config.DIGEST_DIR / f"{target_date}.md"
    stats_file = config.DIGEST_TMP / f"{target_date}.stats.json"
    try:
        if digest_file.exists():
            digest_file.unlink()
        if stats_file.exists():
            stats_file.unlink()
    except Exception as e:
        notify.log_module("digest", f"清 cache 失败: {e}", "warn")
    markdown, source, status = get_or_generate(target_date, force=True)
    return markdown, source, status
