#!/usr/bin/env python3
"""bid-master 统一服务入口（DEV-0042 · 单系统整合版）

原 3242 行单体已拆包至 app/：
  web/      Router + HTTP/SSE 基类
  api/      按域路由（meta/bids/leads/commands/ops/stream）
  services/ 领域服务（lead_gate/lead_store/bid_service/command_engine/…）
  store/    服务自有库（app.db：leads 观察层/审计/事件）
  bootstrap 显式启动序列

API 面统一为 /api/v1/*（契约矩阵 docs/api-contract-matrix.md）。
标域权威在 ~/.bidmaster/truth.db（rules/store.py 唯一写口）。
"""
import app.main

if __name__ == "__main__":
    app.main.main()
