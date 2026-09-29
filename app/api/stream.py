#!/usr/bin/env python3
"""app/api/stream.py · SSE 说明（流本体由 AppHandler._handle_sse 直接处理，不走 Router）"""
# SSE 是长连接流端点，在 http 层特判 /api/v1/stream 后进入 _handle_sse；
# 本模块仅保留文档性占位，保证 api 包结构完整。
SSE_PATH = "/api/v1/stream"
