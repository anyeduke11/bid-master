#!/usr/bin/env python3
"""app/api/bids.py · 标域端点（超集形状：看板字段 ∪ BAW 权威字段）"""
from ..services import bid_service
import store as truth  # rules/store.py（真实层读模型）


def list_bids(req):
    status = req.query.get("status", ["active"])[0]
    return 200, bid_service.all_bids(status)


def get_bid(req):
    code = req.params["code"]
    b = bid_service.find(code)
    if not b:
        return 404, {"err": f"客户不存在: {code}"}
    return 200, b


def deep_dive(req):
    bid_id = req.params["bid_id"]
    return 200, truth.read_bid_detail(bid_id)
