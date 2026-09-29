#!/usr/bin/env python3
"""app/services/summary.py · 周期经营汇总（自 server.py do_GET /api/summary 迁移，聚合口径不变）"""
from datetime import date, timedelta

from . import bid_service


def compute(period="week"):
    today = date.today()
    if period == "week":
        start = today - timedelta(days=today.weekday())  # 本周一
        period_label = f"{start} ~ {today}"
    elif period == "month":
        start = today.replace(day=1)
        period_label = f"{today.year}-{today.month:02d}"
    elif period == "quarter":
        q = (today.month - 1) // 3 + 1
        start = today.replace(month=(q - 1) * 3 + 1, day=1)
        period_label = f"{today.year}-Q{q}"
    else:  # year
        start = today.replace(month=1, day=1)
        period_label = f"{today.year}"

    bids = bid_service.all_bids("all")
    in_range = lambda t: t and t.split()[0] >= start.isoformat()
    created = [b for b in bids if in_range(b.get("created_at", ""))]
    closed = [b for b in bids if in_range(b.get("closed_at", "")) and b.get("lifecycle") in ("closed", "archived")]
    wins = [b for b in closed if b.get("final_outcome") == "win"]
    losses = [b for b in closed if b.get("final_outcome") == "loss"]
    in_range_active = [b for b in bids if b.get("lifecycle") == "active" and in_range(b.get("last_sync", ""))]

    by_industry, by_region, by_tier = {}, {}, {}
    for b in bids:
        k = b.get("industry") or "未分类"
        by_industry[k] = by_industry.get(k, 0) + 1
        k = b.get("region") or "未分类"
        by_region[k] = by_region.get(k, 0) + 1
        k = b.get("tier") or "未分级"
        by_tier[k] = by_tier.get(k, 0) + 1

    by_loss_reason = {}
    for b in losses:
        r = b.get("loss_reason") or "未填"
        by_loss_reason[r] = by_loss_reason.get(r, 0) + 1

    return {
        "period": period,
        "label": period_label,
        "start": start.isoformat(),
        "end": today.isoformat(),
        "metrics": {
            "new_count": len(created),
            "active_count": len(in_range_active),
            "closed_count": len(closed),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate": round(len(wins) / max(len(closed), 1) * 100, 1),
            "est_total": sum(b.get("est_amount", 0) for b in wins),
            "pipeline_total": sum(b.get("est_amount", 0) for b in bids if b.get("lifecycle") == "active"),
        },
        "by_industry": by_industry,
        "by_region": by_region,
        "by_tier": by_tier,
        "by_loss_reason": by_loss_reason,
        "top_clients": sorted(
            [{"code": b["code"], "client": b["client"], "amount": b.get("est_amount", 0),
              "industry": b.get("industry"), "tier": b.get("tier")}
             for b in bids if b.get("est_amount", 0) > 0],
            key=lambda x: -x["amount"])[:5],
    }
