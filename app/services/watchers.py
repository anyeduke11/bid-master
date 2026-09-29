#!/usr/bin/env python3
"""app/services/watchers.py · 后台监听（自 server.py 1159-1274/1357-1379 迁移）

M3 文件监听：5s 轮询 lead 数据面 jsonl（新路径 ~/.bidmaster/leads/），增量入库；
P0+score≥80 自动升级规则提为显式函数（原内嵌在监听循环里）。
freshness 扫描器：6h 周期。
"""
import json
import time
import uuid
from datetime import datetime
from pathlib import Path

from .. import config
from ..store import app_db
from . import bid_service, lead_store, notify

_file_watcher_state = {}  # path -> (mtime, 已读行数)


def parse_lead_line(line):
    """解析 leads.jsonl 单行（兼容 lead_capture.sh 输出字段）。"""
    try:
        d = json.loads(line.strip())
        if not isinstance(d, dict):
            return None
        return {
            "lead_id": d.get("lead_id", ""),  # 保留 jsonl 里的 lead_id（qualify_score 回写一致）
            "ts": d.get("ts", datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
            "title": d.get("title", ""),
            "buyer": d.get("buyer", ""),
            "industry": d.get("industry", ""),
            "region": d.get("region", ""),
            "amount": d.get("amount", 0),
            "deadline": d.get("deadline", ""),
            "published_at": d.get("published_at", ""),
            "source": d.get("source", d.get("channel", "")),
            "link": d.get("link", ""),
            "raw_keywords": d.get("raw_keywords", ""),
            "score": d.get("score", 0),
            "recommend": d.get("recommend", ""),
            "reason": d.get("reason", ""),
        }
    except Exception:
        return None


def maybe_auto_promote(lead):
    """自动升级规则（显式化）：P0 + score≥80 + lifecycle=new → lead.promote（经标准命令管道）。"""
    if not (lead.get("recommend") == "P0"
            and int(lead.get("score", 0) or 0) >= 80
            and lead.get("lifecycle", "new") == "new"):
        return
    from . import command_engine, lead_commands
    lead_id = lead.get("lead_id", "")
    row = app_db.get_lead(lead_id)
    if not row or row["lifecycle"] != "new" or row["promoted_to_bid"]:
        return
    auto_code = f"BB-AUTO-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    status, response, exec_id = command_engine.dispatch(
        "lead.promote",
        {"lead_id": lead_id, "new_code": auto_code},
        idempotency_key=f"m3-auto-{lead_id}-{int(time.time()*1000)}",
        agent_id="m3-watcher",
        _internal=True,
    )
    if status == 200 and response.get("ok"):
        notify.log_module("watcher", f"🤖 M3 自动升级 P0 lead: {lead.get('title', '')[:30]} → {auto_code}", "info")
        notify.sse.broadcast("lead_auto_promoted", {"lead_id": lead_id, "new_bid": auto_code,
                                                    "title": lead.get("title", "")})
    else:
        notify.log_module("watcher", f"⚠️ M3 自动升级失败: status={status} err={response.get('err', '?')}", "warn")


def file_watcher_loop():
    """M3:5s 轮询 lead 数据面 jsonl,只读新增行(用 mtime + 行数定位)。"""
    while True:
        try:
            for f in config.LEAD_WATCH_FILES:
                if not f.exists():
                    continue
                st = f.stat()
                prev_mtime, prev_lines = _file_watcher_state.get(str(f), (0, 0))
                if st.st_mtime == prev_mtime and prev_lines > 0:
                    continue
                with open(f, "r", encoding="utf-8") as fp:
                    lines = fp.readlines()
                new_count = 0
                for line in lines[prev_lines:]:
                    lead = parse_lead_line(line)
                    if not lead or not lead.get("title"):
                        continue
                    if lead_store.save_lead(lead):
                        new_count += 1
                        notify.sse.broadcast("lead_created", {
                            "title": lead["title"], "buyer": lead["buyer"],
                            "industry": lead["industry"], "amount": lead["amount"],
                            "recommend": lead.get("recommend", ""),
                        })
                        maybe_auto_promote(lead)
                if new_count:
                    notify.log_module("watcher", f"📥 M3 监听 {f.name} 新增 {new_count} 条 lead", "info")
                _file_watcher_state[str(f)] = (st.st_mtime, len(lines))
        except Exception as e:
            notify.log_module("watcher", f"监听循环异常: {e}", "warn")
        time.sleep(5)


def start_file_watcher():
    import threading
    threading.Thread(target=file_watcher_loop, daemon=True, name="m3-file-watcher").start()
    notify.log_module("watcher", "M3 文件监听器已启动(5s 轮询 ~/.bidmaster/leads/*.jsonl)", "info")


def start_freshness_scanner():
    """关闭区：后台每 6 小时自动扫描 lead 时效。"""
    def loop():
        while True:
            try:
                time.sleep(6 * 3600)
                result = lead_store.scan_lead_freshness()
                if result["expired"] or result["aging"]:
                    notify.log_module("lifecycle",
                                      f"🔄 自动扫描: 关闭区新增 {len(result['expired'])} 条 · 老化 {len(result['aging'])} 条",
                                      "info")
            except Exception as e:
                print(f"[scanner] freshness 循环失败: {e}", file=__import__("sys").stderr)

    import threading
    threading.Thread(target=loop, daemon=True, name="freshness-scanner").start()
    print(f"[init] 📦 关闭区扫描器已启动(6h 周期,LEAD_FRESH_DAYS={config.LEAD_FRESH_DAYS} 天)", file=__import__("sys").stderr)
