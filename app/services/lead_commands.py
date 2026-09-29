#!/usr/bin/env python3
"""app/services/lead_commands.py · lead.* / collection.sync 命令处理器（自 server.py 1635-1803 迁移）

SQL 纪律：每条 execute 都是全字面量参数化 SQL；字段分支用显式 if/elif（无查表动态执行）。
"""
import json
import os
import sys
import time
from datetime import datetime
from urllib.parse import urlparse

import lifecycle  # rules/lifecycle.py 七段生命周期判定器

from .. import config
from . import bid_service, lead_store, notify
from .command_engine import register_command


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _cmd_collection_sync(conn, params):
    """collection.sync - 外部 Agent 同步观察层(lead)数据（append 默认 / upsert 刷新报告可推导字段）"""
    items = params.get("items", [])
    run_id = params.get("run_id", f"run_{int(time.time())}")
    source = params.get("source", "manual")
    mode = params.get("mode", "append")
    if not items:
        return {"err": "items 为空"}
    inserted = updated = skipped = rejected = 0
    now = _now()
    for it in items:
        try:
            row = conn.execute("SELECT lead_id, link FROM leads WHERE lead_id=?", (it.get("lead_id"),)).fetchone()
            if row:
                if mode != "upsert":
                    skipped += 1
                    continue
                # 「仅原空才补链」语义在 Python 侧判定
                existing_link = row["link"] or ""
                new_link = it.get("link", "") if not existing_link else existing_link
                conn.execute("UPDATE leads SET amount=?, deadline=?, published_at=?, link=?, raw_keywords=?, reason=?, industry=?, buyer_level=?, sub_industry=?, phase=?, agency=COALESCE(NULLIF(?, ''), agency), updated_at=? WHERE lead_id=?",
                             (float(it.get("amount", 0) or 0), it.get("deadline", ""), it.get("published_at", ""),
                              new_link,
                              it.get("raw_keywords", ""), it.get("reason", ""),
                              it.get("industry", ""), it.get("buyer_level", ""), it.get("sub_industry", ""),
                              it.get("phase", ""), it.get("agency", ""), now, it.get("lead_id")))
                updated += 1
                continue
            lead_id = it.get("lead_id", "") or lead_store.derive_lead_id(it.get("title", ""), it.get("buyer", ""))
            conn.execute("INSERT OR IGNORE INTO leads (lead_id, ts, title, buyer, industry, region, amount, deadline, published_at, source, link, raw_keywords, score, recommend, reason, lifecycle, promoted_to_bid, created_at, updated_at, phase, buyer_level, sub_industry, agency) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', '', ?, ?, ?, ?, ?, ?)",
                         (lead_id,
                          now,
                          it.get("title", ""), it.get("buyer", ""),
                          it.get("industry", ""), it.get("region", ""),
                          float(it.get("amount", 0) or 0), it.get("deadline", ""),
                          it.get("published_at", now[:10]),
                          source, it.get("link", ""),
                          it.get("raw_keywords", ""),
                          int(it.get("score", 0) or 0), it.get("recommend", ""),
                          it.get("reason", ""),
                          now, now,
                          it.get("phase", ""), it.get("buyer_level", ""), it.get("sub_industry", ""),
                          it.get("agency", ""),
                          ))
            inserted += 1
        except Exception:
            rejected += 1
    applied = inserted + updated
    run_status = "partially_applied" if rejected else "applied"
    conn.execute("INSERT INTO collection_run (run_id, source, channel_name, status, items_count, applied_count, rejected_count, started_at, completed_at, payload_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (run_id, source, params.get("channel_name", source), run_status,
                  len(items), applied, rejected, _now(), _now(),
                  params.get("payload_hash", "")))
    return {"ok": True, "run_id": run_id, "applied": applied, "rejected": rejected,
            "inserted": inserted, "updated": updated, "skipped": skipped, "mode": mode}


def _cmd_lead_qualify(conn, params):
    """lead.qualify - 人工确认（必须 reason；recommend P0/P1/P2/跳过）"""
    lead_id = params.get("lead_id", "")
    score = int(params.get("score", 0) or 0)
    recommend = params.get("recommend", "")
    reason = params.get("reason", "")
    if recommend not in ("P0", "P1", "P2", "跳过"):
        return {"err": "recommend 必须 P0/P1/P2/跳过"}
    # 兼容: 数字走主键 id，字符串走 lead_id 业务字段（与 lead.promote 一致）
    row = None
    try:
        pk = int(lead_id)
        row = conn.execute("SELECT id FROM leads WHERE id=?", (pk,)).fetchone()
    except (ValueError, TypeError):
        row = None
    if row is None:
        row = conn.execute("SELECT id FROM leads WHERE lead_id=?", (lead_id,)).fetchone()
    if not row:
        return {"err": f"lead 不存在: {lead_id}"}
    if not reason:
        return {"err": "人工确认必须填 reason"}
    conn.execute("UPDATE leads SET score=?, recommend=?, reason=?, lifecycle='reviewed', updated_at=? WHERE lead_id=?",
                 (score, recommend, reason, _now(), lead_id))
    return {"ok": True, "lead_id": lead_id, "score": score, "recommend": recommend}


def _cmd_lead_discard(conn, params):
    """lead.discard - 丢弃 lead（兼容整数主键 id 和字符串 lead_id）"""
    lead_id = params.get("lead_id", "")
    row = None
    try:
        pk = int(lead_id)
        row = conn.execute("SELECT id, lead_id FROM leads WHERE id=?", (pk,)).fetchone()
    except (ValueError, TypeError):
        row = None
    if row is None:
        row = conn.execute("SELECT id, lead_id FROM leads WHERE lead_id=?", (lead_id,)).fetchone()
    if not row:
        return {"err": f"lead 不存在: {lead_id}"}
    row = dict(row)
    real_lead_id = row["lead_id"]
    conn.execute("UPDATE leads SET lifecycle='discarded', updated_at=? WHERE lead_id=?",
                 (_now(), real_lead_id))
    return {"ok": True, "lead_id": real_lead_id}


def _cmd_lead_patch(conn, params):
    """lead.patch - 人工/工具修订 lead 字段（白名单；link 仅 http/https；phase 七段校验）。
    字段分支用显式 if/elif，每条 execute 全字面量参数化 SQL。"""
    lead_id = params.get("lead_id", "")
    fields = params.get("fields", {}) or {}
    row = conn.execute("SELECT id FROM leads WHERE lead_id=?", (lead_id,)).fetchone()
    if not row:
        return {"err": f"lead 不存在: {lead_id}"}
    if not isinstance(fields, dict) or not fields:
        return {"err": "fields 为空"}
    allowed = {"link", "sales_owner", "phase", "recommend", "buyer_level", "sub_industry", "provenance"}
    unknown = [k for k in fields if k not in allowed]
    if unknown:
        return {"err": f"不支持的字段: {unknown}（允许: {sorted(allowed)}）"}
    if "phase" in fields and fields["phase"] not in lifecycle.PHASES:
        return {"err": f"phase 必须是 {lifecycle.PHASES} 之一"}
    if "recommend" in fields and fields["recommend"] not in ("P0", "P1", "P2", ""):
        return {"err": "recommend 必须 P0/P1/P2 或空"}
    if "link" in fields and fields["link"]:
        lu = urlparse(str(fields["link"]))
        if lu.scheme not in ("http", "https"):
            return {"err": "link 仅允许 http/https"}
    now = _now()
    if "link" in fields:
        conn.execute("UPDATE leads SET link=?, updated_at=? WHERE lead_id=?", (fields["link"], now, lead_id))
    if "sales_owner" in fields:
        conn.execute("UPDATE leads SET sales_owner=?, updated_at=? WHERE lead_id=?", (fields["sales_owner"], now, lead_id))
    if "phase" in fields:
        conn.execute("UPDATE leads SET phase=?, updated_at=? WHERE lead_id=?", (fields["phase"], now, lead_id))
    if "recommend" in fields:
        conn.execute("UPDATE leads SET recommend=?, updated_at=? WHERE lead_id=?", (fields["recommend"], now, lead_id))
    if "buyer_level" in fields:
        conn.execute("UPDATE leads SET buyer_level=?, updated_at=? WHERE lead_id=?", (fields["buyer_level"], now, lead_id))
    if "sub_industry" in fields:
        conn.execute("UPDATE leads SET sub_industry=?, updated_at=? WHERE lead_id=?", (fields["sub_industry"], now, lead_id))
    if "provenance" in fields:
        # R4：线索来历留痕（"实际怎么来的"——抓取失败后的人工补录路径），随事件流可查
        conn.execute("UPDATE leads SET provenance=?, updated_at=? WHERE lead_id=?", (str(fields["provenance"])[:500], now, lead_id))
        notify.log_module("leads", f"provenance 登记: {lead_id}", "info", lead_id, {"value": str(fields["provenance"])[:200]})
    return {"ok": True, "lead_id": lead_id, "patched": sorted(fields.keys())}


def _cmd_lead_promote(conn, params):
    """lead.promote - lead 升级为 bid（lead→bid 字段映射与原实现一致；bid 经 bid_service 建 truth 档）"""
    lead_id = params.get("lead_id", "")
    new_code = params.get("new_code", "")
    if not new_code:
        return {"err": "缺 new_code"}
    # 兼容:数字走主键 id,字符串走 lead_id 业务字段
    row = None
    try:
        pk = int(lead_id)
        row = conn.execute("SELECT * FROM leads WHERE id=?", (pk,)).fetchone()
    except (ValueError, TypeError):
        row = None
    if row is None:
        row = conn.execute("SELECT * FROM leads WHERE lead_id=?", (lead_id,)).fetchone()
    if row is None:
        return {"err": f"lead 不存在: {lead_id}"}
    if bid_service.find(new_code):
        return {"err": f"bid code 已存在: {new_code}"}
    lead = dict(row)
    bid_params = {
        "code": new_code,
        "client": lead.get("buyer", "") or (lead.get("title", "") or "")[:30] or "未命名客户",
        "stage": "审查",
        "priority": lead.get("recommend", "P2") if str(lead.get("recommend", "")).startswith("P") else "P2",
        "due_at": str(lead.get("deadline", "") or ""),
        "ai_ready": [f"从 lead {lead_id} 升级: {lead.get('title', '')}"],
        "human_todo": ["首次接触客户", "确认决策人"],
        "industry": lead.get("industry", "") or "",
        "region": lead.get("region", "") or "",
        "est_amount": int(lead.get("amount", 0) or 0),
        "tier": "未分级",
        "link": lead.get("link", "") or "",
        "ltc_stage": "opportunity",
    }
    new = bid_service.create(bid_params)
    if not new:
        return {"err": "create bid 失败"}
    conn.execute("UPDATE leads SET lifecycle='promoted', promoted_to_bid=?, updated_at=? WHERE lead_id=?",
                 (new_code, _now(), lead_id))
    return {"ok": True, "new_bid": new_code, "lead_id": lead_id}


def _cmd_lead_add(conn, params):
    """lead.add - 手动添加一条标讯（看板 02 面板「手动添加」用）。
    字段白名单：title 必填；buyer/link/deadline/published_at/amount/summary 可选。
    lead_id 缺省按 sha256(title|buyer) 派生（与 rules/store.py 一致）；upsert 语义。"""
    title = (params.get("title") or "").strip()
    if not title:
        return {"err": "title 必填"}
    buyer = (params.get("buyer") or "").strip()
    link = (params.get("link") or "").strip()
    if link:
        u = urlparse(link)
        if u.scheme not in ("http", "https"):
            return {"err": "link 仅允许 http/https"}
    deadline = (params.get("deadline") or "").strip()
    published_at = (params.get("published_at") or "").strip() or _now()[:10]
    amount = float(params.get("amount") or 0)
    industry = (params.get("industry") or "").strip()
    region = (params.get("region") or "").strip()
    summary = (params.get("summary") or "").strip()
    agency = (params.get("agency") or "").strip()
    source = (params.get("source") or "manual").strip()
    lead_id = params.get("lead_id") or lead_store.derive_lead_id(title, buyer)

    now = _now()
    existing = conn.execute("SELECT id FROM leads WHERE lead_id=?",
                            (lead_id,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE leads SET title=?, buyer=?, agency=COALESCE(NULLIF(?, ''), agency), "
            "link=COALESCE(NULLIF(?, ''), link), "
            "deadline=?, published_at=?, amount=?, reason=?, "
            "industry=?, region=?, updated_at=? WHERE lead_id=?",
            (title, buyer, agency, link, deadline, published_at, amount,
             summary or f"手动添加 · {source}",
             industry, region, now, lead_id),
        )
        return {"ok": True, "lead_id": lead_id, "mode": "updated"}
    conn.execute(
        "INSERT INTO leads (lead_id, ts, title, buyer, industry, region, amount, "
        "deadline, published_at, source, link, raw_keywords, score, recommend, "
        "reason, lifecycle, promoted_to_bid, created_at, updated_at, phase, "
        "buyer_level, sub_industry, agency) VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', 0, '', ?, 'new', '', ?, ?, '', '', '', ?)",
        (lead_id, now, title, buyer, industry, region, amount, deadline, published_at,
         source, link, summary or f"手动添加 · {source}", now, now, agency),
    )
    return {"ok": True, "lead_id": lead_id, "mode": "inserted"}


def _cmd_lead_refresh_status(conn, params):
    """lead.refresh_status - 触发状态复核（看板 02 面板「立即复核/复核全部」用）。

    命令本身不直接抓网页（避免长事务卡住看板），只调度后台子进程跑
    lead_status_check.py：带 lead_id 复核单条；不带 lead_id 批量复核全部（DEV-0081，
    批量走 scheduler 的单跑执行器——与调度轮次同一条代码路径）。
    """
    lead_id = params.get("lead_id", "").strip()
    if not lead_id:
        notify.log_module("leads", "批量复核全部 lead（后台调度，--limit 50）", "info")
        try:
            import threading
            from ..services import scheduler as _sched
            threading.Thread(target=_sched.run_status_check_now, daemon=True,
                             name="lead-status-batch").start()
        except Exception as e:
            return {"ok": True, "mode": "batch", "note": f"已调度但后台启动失败：{e}"}
        return {"ok": True, "mode": "batch", "scheduled": True}
    row = conn.execute("SELECT id, link FROM leads WHERE lead_id=?",
                       (lead_id,)).fetchone()
    if not row:
        return {"err": f"lead 不存在: {lead_id}"}
    if not row["link"]:
        return {"err": "lead 无原文链接，无法复核"}
    conn.execute(
        "INSERT INTO events (ts, type, level, module, api, code, msg, payload) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (_now(), "status_transition", "info", "lead_status_check",
         "lead.refresh_status", "STATUS_REFRESH_SCHEDULED",
         f"{lead_id} 触发单条复核",
         json.dumps({"lead_id": lead_id}, ensure_ascii=False)),
    )
    try:
        env = os.environ.copy()
        env.setdefault("BIDMASTER_HOME", str(config.BIDMASTER_HOME))  # DEV-0081：原 config.HOME 不存在（必 AttributeError）
        subprocess.Popen(
            [sys.executable, str(config.REPO / "rules" / "lead_status_check.py"),
             "--lead", lead_id, "--limit", "1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env, start_new_session=True,
        )
    except Exception as e:
        return {"ok": True, "lead_id": lead_id,
                "note": f"已调度但后台启动失败：{e}"}
    return {"ok": True, "lead_id": lead_id, "scheduled": True}


def _cmd_lead_import_xlsx(conn, params):
    """lead.import_xlsx - 看板 02 面板 xlsx 拖拽上传入口（前端 base64 + 元数据）。
    严格模式由前端声明；后端落临时文件 → 调 import_xlsx_leads.py → 同步 leads。

    params:
      filename: 原始文件名
      payload_b64: 文件 base64（不允许落库）
      sheet: 数据 sheet（默认 标讯明细）
      strict: bool（默认 True；False 走兼容模式）
    """
    import base64
    import subprocess
    import tempfile
    filename = (params.get("filename") or "uploaded.xlsx").strip()
    b64 = params.get("payload_b64", "")
    sheet = params.get("sheet", "标讯明细")
    strict = bool(params.get("strict", True))
    if not b64:
        return {"err": "payload_b64 必填"}

    try:
        raw = base64.b64decode(b64)
    except Exception as e:
        return {"err": f"base64 解码失败：{e}"}
    if len(raw) > 20 * 1024 * 1024:
        return {"err": "xlsx > 20MB 拒绝"}

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tf:
        tf.write(raw)
        tmp_path = tf.name

    cmd = [sys.executable, str(config.REPO / "rules" / "import_xlsx_leads.py"),
           tmp_path, "--sheet", sheet, "--no-scan"]
    if not strict:
        cmd.append("--no-strict")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        ok = proc.returncode == 0
        return {
            "ok": ok,
            "filename": filename,
            "strict": strict,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:] if proc.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired:
        return {"err": "导入超时（>120s）"}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass




def register_all():
    register_command("collection.sync", "collection", _cmd_collection_sync,
                     "外部 Agent 同步 lead 数据（append/upsert；lead_id 缺省按 sha256(title|buyer) 派生）",
                     schema={"items": "list[lead]", "mode": "append|upsert", "source": "str"})
    register_command("lead.add", "platform", _cmd_lead_add,
                     "手动添加一条标讯（看板 02 面板；title 必填）",
                     schema={"title": "str", "buyer?": "str", "agency?": "str(招标代理)",
                             "link?": "url",
                             "deadline?": "YYYY-MM-DD", "published_at?": "YYYY-MM-DD",
                             "amount?": "float(万元)", "summary?": "str", "source?": "str"})
    register_command("lead.qualify", "platform", _cmd_lead_qualify,
                     "人工确认 lead 评分（必须 reason）", idempotent=False,
                     schema={"lead_id": "str", "recommend": "P0|P1|P2|跳过", "reason": "str"})
    register_command("lead.discard", "platform", _cmd_lead_discard,
                     "丢弃 lead（兼容整数主键 id 和字符串 lead_id）",
                     schema={"lead_id": "str"})
    register_command("lead.patch", "platform", _cmd_lead_patch,
                     "人工修订 lead 字段(销售/阶段/补链/优先级/级别行业/provenance 来历)",
                     schema={"lead_id": "str", "fields": "map(link|sales_owner|phase|recommend|buyer_level|sub_industry|provenance)"})
    register_command("lead.promote", "platform", _cmd_lead_promote,
                     "lead 升级为 bid", schema={"lead_id": "str", "new_code": "str"})
    register_command("lead.refresh_status", "platform", _cmd_lead_refresh_status,
                     "立即复核单条 lead 状态（后台 spawn lead_status_check.py）",
                     idempotent=False,
                     schema={"lead_id": "str"})
    register_command("lead.import_xlsx", "platform", _cmd_lead_import_xlsx,
                     "看板 02 面板 xlsx 拖拽上传（base64 → 临时文件 → 调 import_xlsx_leads.py）",
                     idempotent=False,
                     schema={"filename": "str", "payload_b64": "base64",
                             "sheet?": "str", "strict?": "bool"})
