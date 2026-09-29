#!/usr/bin/env python3
"""consistency.py · 跨标一致性检查（W4 4.3 挂 08:30 cron → alerts.json）

设计依据：docs/baw-design-v3.md §8.3（时间线与跨标一致性）
────────────────────────────────────────────────────────────────
检查项（数据稀疏时优雅降级，产"无数据"说明而非误报）：
  1. 证照有效期：kb/index/certs.json 中 valid_until 已过期或在缓冲期内的 → alert
  2. 人员在投占用：kb/index/people.json 中 bids 字段跨在投标的的占用冲突 → alert
  3. 阶段停滞：bids.jsonl 中停留在 S3+ 且 updated_at 超过 stall_days 的标 → 提醒
输出：~/.bidmaster/alerts.json（watcher/看板消费；status=final）
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA_ROOT = Path.home() / ".bidmaster"
KB = REPO / "kb"
CERTS = KB / "index" / "certs.json"
PEOPLE = KB / "index" / "people.json"
ALERTS = DATA_ROOT / "alerts.json"
CERT_BUFFER_DAYS = 90
STALL_DAYS = 21


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def checks() -> dict:
    alerts = []
    scopes = []
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import store as _store

    # 1) 证照有效期（P3'-1 起读 kb_assets 表，JSON 索引降为导出）
    if CERTS.exists():
        scopes.append("certs")
        rows = _store.kb_assets_by_domain("certs")
        for it in rows:
            vu = (it.get("valid_until") or "").strip()
            if not vu:
                continue
            try:
                expire = datetime.fromisoformat(str(vu))
            except ValueError:
                continue
            left = (expire - datetime.now(expire.tzinfo)).days
            name = it.get("name", "")[:40]
            aid = it.get("id", "")
            if left < 0:
                alerts.append({"type": "cert_expired", "severity": "高",
                               "item": aid, "name": name,
                               "detail": f"证照已过期 {vu}（剩余 {left} 天）"})
            elif left <= CERT_BUFFER_DAYS:
                alerts.append({"type": "cert_expiring", "severity": "中",
                               "item": aid, "name": name,
                               "detail": f"证照 {vu} 到期（剩 {left} 天，缓冲 {CERT_BUFFER_DAYS} 天）"})
        if not rows:
            scopes.append("certs(空)")

    # 2) 人员在投占用（读 kb_assets 表 people 域，raw 内 bids 列表）
    people_rows = _store.kb_assets_by_domain("people")
    scopes.append("people")
    occupy = {}
    for row in people_rows:
        try:
            raw = json.loads(row.get("raw") or "{}")
        except Exception:
            continue
        for b in raw.get("bids", []) or []:
            occupy.setdefault(str(b), []).append(row.get("id"))
    for b, ids in occupy.items():
        if len(ids) > 1:
            alerts.append({"type": "person_conflict", "severity": "高",
                           "item": b, "detail": f"人员在多标占用：{ids}"})

    # 4) 教训衰减（P3'-3）：被取代（沉淀）超 1 年的教训提醒归档；lessons 表为权威
    try:
        stale_cutoff = datetime.now().astimezone() - timedelta(days=365)
        for r in _store._conn().execute("SELECT id, scenario, status, created_at FROM lessons WHERE status LIKE '沉淀%'"):
            created = r["created_at"] or ""
            if created and created[:10] <= stale_cutoff.date().isoformat():
                alerts.append({"type": "lesson_decay", "severity": "低",
                               "item": r["id"], "detail": f"沉淀教训 {r['id']} 已超 1 年，建议归档"})
    except Exception:
        pass

    # 5) 阶段停滞（DEV-0081：改读 truth.db——原 bids.jsonl 已退役，旧实现静默失能）
    scopes.append("stall")
    for r in _store.load_bids():
        if r.get("kind") == "demo":
            continue
        st, upd = r.get("stage", "S0"), r.get("updated_at", "")
        if st in ("S0", "S1", "S2") or not upd:
            continue
        try:
            age = (datetime.now().astimezone() - datetime.fromisoformat(upd)).days
        except ValueError:
            continue
        if age >= STALL_DAYS:
            alerts.append({"type": "stage_stall", "severity": "低", "item": r.get("bid_id"),
                           "detail": f"停留在 {st} 已 {age} 天（阈值 {STALL_DAYS} 天）"})

    if not scopes:
        alerts.append({"type": "no_data", "severity": "提示",
                       "detail": "kb/index 证照与人员数据为空，一致性检查待数据录入后生效"})
    return {"status": "final", "generated_at": _now(), "scopes": scopes,
            "alert_count": len(alerts), "alerts": alerts}


def main() -> int:
    rep = checks()
    ALERTS.parent.mkdir(parents=True, exist_ok=True)
    ALERTS.write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ alerts.json 更新：{rep['alert_count']} 条（范围：{','.join(rep['scopes']) or '无'}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
