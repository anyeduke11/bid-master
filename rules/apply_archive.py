#!/usr/bin/env python3
"""apply_archive.py · 归档提案幂等应用（W4 4.4 · S8→S9 飞轮执行器）

设计依据：docs/baw-design-v3.md §6.4（飞轮门禁强制）、acceptance §3.6（archivist 专项）
────────────────────────────────────────────────────────────────
前置（S8→S9 门禁已保证）：proposal.json status=confirmed（人工采纳）+ 脱敏干净 + supersession 完整。
本脚本动作（幂等，双跑 no-op）：
  1. cases/bids_history 入 kb/index：按 proposal 指纹登记（applied-ledger.json 判重）
  2. lessons 入 memory/lessons.md：分配下一个可用 L-* ID（扫描现存最大号），
     supersession 指向的旧教训若存在则在链索引标注「已被取代→沉淀」
  3. proposal 状态 confirmed → applied（applied_at 落盘）
幂等保证：ledger 存在相同 proposal 指纹 → 直接跳过（no-op）。

用法：
  python3 rules/apply_archive.py --bid <bid_id> [--dry-run]
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

DATA_ROOT = Path.home() / ".bidmaster"
KB = Path.home() / "Documents" / "bid-master" / "kb"
LEDGER = DATA_ROOT / "memory" / "applied-ledger.json"
LESSONS = DATA_ROOT / "memory" / "lessons.md"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sha256(text: str) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _next_lesson_id(lessons_text: str) -> str:
    ids = [int(m) for m in re.findall(r"L-(\d+)", lessons_text)]
    return f"L-{(max(ids) + 1) if ids else 1}"


def apply(bid_id: str, dry: bool) -> int:
    prop_p = DATA_ROOT / "bids" / bid_id / "archive" / "proposal.json"
    if not prop_p.exists():
        print(f"❌ 缺提案 {prop_p}")
        return 1
    prop_text = prop_p.read_text(encoding="utf-8")
    prop = json.loads(prop_text)
    # 幂等键：bid_id + 内容指纹（剔除 status/applied_at 等本脚本自己会改的字段，双跑才能命中）
    content_key = _sha256(json.dumps({k: v for k, v in sorted(prop.items())
                                      if k not in ("status", "applied_at")}, ensure_ascii=False, sort_keys=True))
    ledger = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    if ledger.get(bid_id, {}).get("content_key") == content_key:
        print(f"✅ no-op：该提案已于 {ledger[bid_id].get('applied_at')} 应用（幂等，双跑跳过）。")
        return 0
    if prop.get("status") == "applied" and bid_id in ledger:
        print("⚠ proposal 已应用但内容有变：按新提案处理（人工确认状态会重新要求 confirmed）。")
    if prop.get("status") != "confirmed":
        print(f"⛔ proposal status={prop.get('status')!r}：仅 confirmed（人工采纳后）可应用。")
        return 1

    # 1) lessons：分配新 ID + supersession 旧条目标注沉淀
    lessons_text = LESSONS.read_text(encoding="utf-8") if LESSONS.exists() else ""
    id_map, new_lines = {}, []
    for les in prop.get("lessons") or []:
        new_id = _next_lesson_id(lessons_text + "\n".join(new_lines))
        old = les.get("supersession", "无")
        id_map[les.get("id", "?")] = new_id
        new_lines.append(f"- {new_id}（{_now()[:10]}，{bid_id} 归档）{les.get('scenario', '')}：{les.get('lesson', '')}"
                         f" 证据：{les.get('evidence', '无')}。supersession: {old}")
        if old and old != "无" and f"{old} " in lessons_text:
            lessons_text = re.sub(rf"(\|\s*{re.escape(old)}\s*\|[^|]*\|) active(\s*\|)",
                                  r"\1 沉淀（被 "
                                  + new_id + " 取代）\\2", lessons_text)
            lessons_text = lessons_text.replace(f"| {old} |", f"| {old} |", 1)
    # 2) kb：案例登记（不复制原件，只登记指针；按 bid_id 去重——重应用时替换而非追加）
    kb_line = None
    kb_p = KB / "index" / "bids_history.json"
    if kb_p.exists() and prop.get("result"):
        kb_idx = json.loads(kb_p.read_text(encoding="utf-8"))
        kb_idx.setdefault("items", [])
        entry = {
            "id": bid_id, "client_alias": prop.get("client_alias", bid_id), "project": "",
            "stage_reached": "S9", "result": prop.get("result"), "lessons": [id_map.get(l.get("id")) for l in prop.get("lessons", [])],
            "file": f"~/.bidmaster/bids/{bid_id}/archive/", "fingerprint": content_key,
            "sensitivity": "L2", "status": "confirmed（apply_archive 登记）", "updated_at": _now()}
        kb_idx["items"] = [e for e in kb_idx["items"] if e.get("id") != bid_id] + [entry]
        kb_line = f"{len(kb_idx['items'])} 条"

    if dry:
        print(f"[dry] 将应用：lessons 新增 {len(new_lines)} 条（{list(id_map.values())}）；kb/bids_history 登记（{kb_line}）；proposal→applied")
        for ln in new_lines:
            print("   ", ln[:90])
        return 0

    if new_lines:
        # P3'-2 lessons 权威层：写入 lessons 表（store 唯一写口）并自动导出 md 渲染
        import store as _store
        _store.init()
        for new_id in id_map.values():
            scen, body = "", ""
            for les in prop.get("lessons") or []:
                if les.get("id") == new_id:
                    scen, body = les.get("scenario", ""), les.get("lesson", "")
            _store.upsert_lesson(new_id, scen, body, "无")
        _store.export_lessons_md()
    if kb_line:
        kb_p.write_text(json.dumps(kb_idx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prop["status"] = "applied"
    prop["applied_at"] = _now()
    prop_p.write_text(json.dumps(prop, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ledger[bid_id] = {"content_key": content_key, "applied_at": _now(), "lessons": id_map}
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ 应用完成：lessons +{len(new_lines)}（{list(id_map.values())}）；kb bids_history 已登记；proposal→applied。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="归档提案幂等应用（S8→S9 飞轮执行器）")
    ap.add_argument("--bid", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    return apply(a.bid, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
