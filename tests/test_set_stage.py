#!/usr/bin/env python3
"""test_set_stage.py · 门禁安全带测试（make gate 挂载）

对五道门禁做"应拦必拦、应放必放"断言 + 登记制/机检接线/指纹保护断言（架构审查修复验证）。
夹具使用独立 demo bid（kind=demo），真实层写入不影响 real 标；测试结束自清（不留 demo 痕迹）。
实现：进程内调 rules/set_stage.main()（argv 注入 + stdout 捕获），无 subprocess。
运行：python3 tests/test_set_stage.py；退出 0=全过。
"""
import io
import json
import shutil
import sys
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "rules"))
import store  # noqa: E402 — 真实层（测试与断言共用）
DATA = Path.home() / ".bidmaster"
BID = "2026-gate-selftest"   # 含 "test" → kind=demo，不污染 real

RESULTS = []


def _call(args: list, bid_id: str = BID) -> tuple:
    """进程内执行 set_stage.main()：argv 注入 + stdout 捕获。返回 (rc, 输出文本)。"""
    import set_stage as ss
    old = sys.argv
    sys.argv = ["set_stage.py", "--bid", bid_id] + list(args)
    buf = io.StringIO()
    rc = 0
    try:
        with redirect_stdout(buf):
            rc = ss.main() or 0
    except SystemExit as e:
        rc = e.code or 0
    finally:
        sys.argv = old
    return rc, buf.getvalue()


def _ws():
    return DATA / "bids" / BID


def _w(rel, obj):
    p = _ws() / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def _reg(kind, path, status="registered"):
    store.register_artifact(BID, kind, str(path), status=status, producer="gate-test")


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


def main() -> int:
    import store
    store.init()
    c = store._conn()
    # 清场（幂等重跑）
    with c:
        c.execute("DELETE FROM stage_history WHERE bid_id=?", (BID,))
        c.execute("DELETE FROM artifacts WHERE bid_id=?", (BID,))
        c.execute("DELETE FROM bids WHERE bid_id=?", (BID,))
    shutil.rmtree(_ws(), ignore_errors=True)
    _ws().mkdir(parents=True, exist_ok=True)

    # ① bootstrap（逃生舱）+ 逐级/回退
    rc, _ = _call(["--bootstrap", "S2"])
    check("bootstrap S2", rc == 0)
    rc, out = _call(["--to", "S4"])
    check("跳级拦截", rc == 2 and "跳级" in out)
    rc, out = _call(["--to", "S1"])
    check("回退拦截", rc == 2 and "只前进" in out)

    # ② S2→S3 门禁：lessons_applied 校验（真交叉验证）
    _w("data/stage0.json", {"lessons_applied": []})
    rc, out = _call(["--to", "S3"])
    check("S2→S3 空 lessons 拦截", rc == 2 and "lessons_applied 为空" in out)
    _w("data/stage0.json", {"lessons_applied": ["L-999"]})
    rc, out = _call(["--to", "S3"])
    check("S2→S3 无效教训 ID 拦截", rc == 2 and "不存在" in out)
    _w("data/stage0.json", {"lessons_applied": ["L-1"]})
    rc, _ = _call(["--to", "S3"])
    check("S2→S3 有效教训放行", rc == 0)

    # ③ S3→S4：对账
    rc, out = _call(["--to", "S4"])
    check("S3→S4 缺对账拦截", rc == 2)
    _w("data/hits_recon.json", {"items": [{"keyword": "k", "status": "收录", "reason": "r"}]})
    rc, _ = _call(["--to", "S4"])
    check("S3→S4 对账齐放行", rc == 0)

    # ④ S4→S5：完整性 + 覆盖 + 匹配率 + verify_draft 机检（读登记表）
    rc, out = _call(["--to", "S5"])
    check("S4→S5 缺完整性拦截", rc == 2)
    _w("data/completeness.json", {"result": "PASS", "checks": []})
    _w("data/spec.json", {"scoring_points": [
        {"id": "SP1", "chapter": "ch01", "material_ptrs": ["kb/slices/x.md#L1"], "cites": ["P1"]}]})
    rc, out = _call(["--to", "S5"])
    check("S4→S5 缺 verify_draft 登记/机检拦截", rc == 2 and "verify_draft" in out)
    vd = _w("verify/verify_draft_ch01.json", {"pass": True, "blockers": []})
    _reg("verify_draft", vd)                                  # 登记制：写文件后必须登记
    rc, out = _call(["--to", "S5"])
    check("S4→S5 机检过放行", rc == 0)
    # 门禁提升断言（P1-2 状态机：放行后 verify_draft 应被提升为 final）
    row = store.latest_artifact(BID, "verify_draft")
    check("S4→S5 放行后门禁提升 final", row and row["status"] == "final")
    # 机检不过必须拦（防"文件存在即过"）——直接调 gate 函数验证
    import set_stage as ss
    _w("verify/verify_draft_ch01.json", {"pass": False, "blockers": ["cite 违规"]})
    _reg("verify_draft", vd)                                  # 篡改后重新登记（模拟新版报告）
    ok, blockers, _ = ss.gate_s4_s5(_ws(), {})
    check("S4→S5 verify_draft FAIL 必拦", not ok and any("机检未过" in b for b in blockers))

    # ④b DEV-0056：素材率门禁可选忽略（--ignore-material）——其余检查不豁免、留痕进 extra
    _w("data/spec.json", {"scoring_points": [
        {"id": "SP1", "chapter": "ch01", "material_ptrs": [], "cites": ["P1"]}]})   # 素材率 0%
    _w("verify/verify_draft_ch01.json", {"pass": True, "blockers": []})
    _reg("verify_draft", _ws() / "verify/verify_draft_ch01.json")
    ok, blockers, extra = ss.gate_s4_s5(_ws(), {})
    check("S4→S5 素材率0%默认必拦", not ok and any("匹配率" in b for b in blockers))
    ok, blockers, extra = ss.gate_s4_s5(_ws(), {"ignore_material": "人员证书待补，先行推进审查"})
    check("S4→S5 ignore-material 放行并留痕",
          ok and extra.get("material_gate") == "ignored" and bool(extra.get("ignore_reason")))
    _w("verify/verify_draft_ch01.json", {"pass": False, "blockers": ["cite 违规"]})
    _reg("verify_draft", _ws() / "verify/verify_draft_ch01.json")
    ok, blockers, _ = ss.gate_s4_s5(_ws(), {"ignore_material": "x"})
    check("S4→S5 ignore 不豁免机检 FAIL", not ok and any("机检未过" in b for b in blockers))
    rc, out = _call(["--to", "S7", "--ignore-material", "x"])
    check("ignore-material 非法迁移拒绝", rc in (2, 3))
    debt = ss.material_debt(BID)
    check("material_debt 盘点缺口", debt.get("ok") and debt.get("missing")
          and debt["missing"][0].get("id") == "SP1")

    # ⑤ S5→S6：审计 + locator 复算 + verify_audit 接线 + 签核
    rc, out = _call(["--to", "S6"])
    check("S5→S6 无审计拦截", rc == 2 and "无审计记录" in out)
    _w("audit/audit-r1.json", {"round": 1, "findings": [], "status": "final"})
    rc, out = _call(["--to", "S6"])
    check("S5→S6 缺 locator 拦截", rc == 2 and "locator" in out)
    loc = _w("verify/locator-report.json",
             {"bid_id": BID, "hit_rate": 0.5, "status": "registered",
              "samples": [{"quote": "a", "hit": True}, {"quote": "b", "hit": False}]})
    _reg("locator", loc)
    rc, out = _call(["--to", "S6"])
    check("S5→S6 复算 hit_rate 不达标拦截（0.5<95%）", rc == 2 and ("复算" in out or "95%" in out))
    _w("verify/locator-report.json",
       {"bid_id": BID, "hit_rate": 1.0, "status": "registered", "samples": [{"quote": "a", "hit": True}]})
    _reg("locator", _ws() / "verify/locator-report.json")
    rc, out = _call(["--to", "S6"])
    check("S5→S6 缺 verify_audit 机检拦截（P1-2 接线）", rc == 2 and "verify_audit" in out)
    va = _w("verify/verify_audit_r1.json", {"pass": True})
    _reg("verify_audit", va)
    rc, out = _call(["--to", "S6"])
    check("S5→S6 缺签核拦截", rc == 2 and "签核" in out)
    rc, _ = _call(["--to", "S6", "--sign-off", "Duke"])
    check("S5→S6 全齐放行", rc == 0)
    # 门禁提升断言（locator/verify_audit 放行后应升 final）
    row_l = store.latest_artifact(BID, "locator")
    row_a = store.latest_artifact(BID, "verify_audit")
    check("S5→S6 放行后提升 final",
          row_l and row_l["status"] == "final" and row_a and row_a["status"] == "final")
    # 真实层终态断言
    b = store.get_bid(BID)
    check("真实层终态 S6", b and b.get("stage") == "S6" and b.get("kind") == "demo")

    # ⑦ R1：classified 壳门禁全豁——同一迁移对 demo 拦、对壳放（对照即回归断言）
    BID_CL = BID + "-classified"
    with c:
        c.execute("DELETE FROM stage_history WHERE bid_id=?", (BID_CL,))
        c.execute("DELETE FROM artifacts WHERE bid_id=?", (BID_CL,))
        c.execute("DELETE FROM gate_attempts WHERE bid_id=?", (BID_CL,))
        c.execute("DELETE FROM bids WHERE bid_id=?", (BID_CL,))
    store.create_bid(BID_CL, "S2", kind="classified")   # 壳：无任何工作区产物
    rc, out = _call(["--json", "--to", "S3"], bid_id=BID_CL)
    check("壳 S2→S3 豁免放行（demo 同迁移被拦）", rc == 0 and '"gate_exempt": true' in out,
          out[:120])
    rc, out = _call(["--json", "--to", "S4"], bid_id=BID_CL)
    check("壳 S3→S4 豁免放行（无 hits_recon）", rc == 0 and "gate_exempt" in out, out[:120])
    row = c.execute("SELECT ok FROM gate_attempts WHERE bid_id=? ORDER BY id DESC LIMIT 1", (BID_CL,)).fetchone()
    check("壳门禁尝试留痕 ok=1", row is not None and row["ok"] == 1)
    bcl = store.get_bid(BID_CL)
    check("壳终态 S4/kind 不变", bcl and bcl["stage"] == "S4" and bcl["kind"] == "classified")
    # 素材债守卫：壳传 --ignore-material 不应产生材料债工单
    rc, out = _call(["--json", "--to", "S5", "--ignore-material", "壳测试"], bid_id=BID_CL)
    has_debt = c.execute("SELECT 1 FROM tickets WHERE ticket_id=?", (f"TIK-material-{BID_CL}",)).fetchone()
    check("壳 S4→S5 豁免放行且不开材料债", rc == 0 and has_debt is None, f"rc={rc} debt={bool(has_debt)}")
    # 壳全生命周期（T6 收官）：S5→S9 豁免语义——无签核过 S5→S6、无 proposal 过 S8→S9（壳无内容可审/可脱敏）
    rc, out = _call(["--json", "--to", "S6"], bid_id=BID_CL)
    check("壳 S5→S6 豁免放行（无 --sign-off）", rc == 0 and "gate_exempt" in out, out[:120])
    rc, _ = _call(["--json", "--to", "S7"], bid_id=BID_CL)
    check("壳 S6→S7 放行（本无门禁）", rc == 0)
    rc, _ = _call(["--json", "--to", "S8"], bid_id=BID_CL)
    check("壳 S7→S8 放行（本无门禁）", rc == 0)
    rc, out = _call(["--json", "--to", "S9"], bid_id=BID_CL)
    check("壳 S8→S9 豁免放行（无 proposal）", rc == 0 and "gate_exempt" in out, out[:120])
    bcl = store.get_bid(BID_CL)
    check("壳全生命周期终态 S9", bcl and bcl["stage"] == "S9" and bcl["kind"] == "classified")

    # 汇总
    failed = [r for r in RESULTS if not r[1]]
    for name, ok_, detail in RESULTS:
        print(("✅" if ok_ else "❌"), name, detail[:60] if not ok_ else "")
    print(f"\n门禁安全带测试：{len(RESULTS) - len(failed)}/{len(RESULTS)} 通过")
    # 自清：不留 demo 痕迹（真实层行 + 工作区；make gate 每次全新）
    with c:
        c.execute("DELETE FROM stage_history WHERE bid_id=?", (BID,))
        c.execute("DELETE FROM artifacts WHERE bid_id=?", (BID,))
        c.execute("DELETE FROM bids WHERE bid_id=?", (BID,))
        c.execute("DELETE FROM stage_history WHERE bid_id=?", (BID_CL,))
        c.execute("DELETE FROM artifacts WHERE bid_id=?", (BID_CL,))
        c.execute("DELETE FROM gate_attempts WHERE bid_id=?", (BID_CL,))
        c.execute("DELETE FROM tickets WHERE bid_id=?", (BID_CL,))
        c.execute("DELETE FROM bids WHERE bid_id=?", (BID_CL,))
    shutil.rmtree(_ws(), ignore_errors=True)
    store.export_jsonl()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
