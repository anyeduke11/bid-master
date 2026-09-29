#!/usr/bin/env python3
"""test_store_readnow.py · R3 镜子性读模型测试（T1 · DEV-0074）

密封 BIDMASTER_HOME（tempfile），全程不碰真实数据面。
覆盖：KINDS+classified 校验 / kind_for() 去重 / epoch bump（create_bid、upsert_ticket）/
read_now 死线扫描（分层+排除+脏值容错）/ S7 复盘派生提醒（>1d 出现、>7d 降级、closed 排除）。
运行：python3 tests/test_store_readnow.py；退出 0=全过。
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_TMP = tempfile.mkdtemp(prefix="bidmaster-t1-")
os.environ["BIDMASTER_HOME"] = _TMP  # 必须先于 import store（模块级 DATA_ROOT）
sys.path.insert(0, str(REPO / "rules"))
import store  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


def _iso(dt):
    return dt.astimezone().isoformat(timespec="seconds")


def _mk_bid(bid_id, kind="real", stage="S0", due_at="", lifecycle="active"):
    store.create_bid(bid_id, stage, kind=kind)
    store.upsert_bid_profile(bid_id, {"code": bid_id, "client": bid_id + "客户",
                                      "due_at": due_at, "lifecycle": lifecycle})


def _backdate_s7(bid_id, days):
    """把标置为 S7 并写入回拨 N 天的进入时间（直写 stage_history，测试专用）。"""
    c = store._conn()
    with c:
        c.execute("UPDATE bids SET stage=? WHERE bid_id=?", ("S7", bid_id))
        c.execute("INSERT INTO stage_history (bid_id, from_stage, to_stage, ts) VALUES (?,?,?,?)",
                  (bid_id, "S6", "S7", _iso(datetime.now() - timedelta(days=days))))


def _now_items():
    return store.read_now()["items"]


def main() -> int:
    store.init()
    today = date.today()
    d = lambda off: (today + timedelta(days=off)).isoformat()  # noqa: E731

    # ① KINDS + classified 校验
    check("KINDS 含 classified", "classified" in store.KINDS)
    try:
        store.create_bid("t1-kind-ok", "S0", kind="classified")
        check("create_bid(classified) 放行", True)
    except ValueError:
        check("create_bid(classified) 放行", False, "被 KINDS 校验拒绝")
    try:
        store.create_bid("t1-kind-bad", "S0", kind="bogus")
        check("create_bid(bogus) 拒绝", False, "非法 kind 未被拦截")
    except ValueError:
        check("create_bid(bogus) 拒绝", True)

    # ② kind_for() 去重（R7：bid_service/set_stage 共用入口）
    check("kind_for demo 标记", store.kind_for("2026-x-demo-1") == "demo")
    check("kind_for 常规 real", store.kind_for("2026-REAL01-aqfw") == "real")
    check("kind_for note 含 demo", store.kind_for("2026-plain", bootstrapped=True, note="kanban-demo 演示") == "demo")

    # ③ epoch bump（R3：create_bid / upsert_ticket 产生变更信号；
    # DEV-0081 扩展：upsert_bid_profile 也 bump——_mk_bid = create(+1) + profile(+1)，共 +2）
    e0 = store.get_epoch()
    _mk_bid("t1-ep")
    e1 = store.get_epoch()
    check("create_bid bump epoch", e1 == e0 + 2, f"{e0} → {e1}（create+profile 各一次）")
    store.upsert_ticket("TIK-t1-epoch", "gate", "generated", "t1-ep")
    e2 = store.get_epoch()
    check("upsert_ticket bump epoch", e2 == e1 + 1, f"{e1} → {e2}")

    # ④ read_now 死线扫描（分层 + 排除 + 容错）
    _mk_bid("t1-overdue", due_at=d(-2) + " 17:00")
    _mk_bid("t1-today", due_at=d(0))
    _mk_bid("t1-soon", due_at=d(3) + " 09:00")
    _mk_bid("t1-far", due_at=d(30))
    _mk_bid("t1-closed", due_at=d(-1), lifecycle="closed")
    _mk_bid("t1-cont", due_at="持续")
    _mk_bid("t1-dirty", due_at="见附件说明")
    _mk_bid("t1-demo", kind="demo", due_at=d(-5))
    dl = {i.get("bid_id"): i for i in _now_items() if i.get("kind") == "deadline"}
    check("死线 overdue 分层", dl.get("t1-overdue", {}).get("severity") == "overdue")
    check("死线 today 分层", dl.get("t1-today", {}).get("severity") == "today")
    check("死线 soon 分层", dl.get("t1-soon", {}).get("severity") == "soon")
    check("死线 >7d 不出现", "t1-far" not in dl)
    check("死线 closed 排除", "t1-closed" not in dl)
    check("死线 '持续' 容错", "t1-cont" not in dl)
    check("死线脏值容错", "t1-dirty" not in dl)
    check("死线 demo 排除", "t1-demo" not in dl)

    # ⑤ read_now S7 复盘派生提醒
    _mk_bid("t1-retro2")
    _backdate_s7("t1-retro2", 2)
    _mk_bid("t1-retro9")
    _backdate_s7("t1-retro9", 9)
    _mk_bid("t1-retro0")
    _backdate_s7("t1-retro0", 0)
    _mk_bid("t1-retro-closed", lifecycle="closed")
    _backdate_s7("t1-retro-closed", 3)
    rt = {i.get("bid_id"): i for i in _now_items() if i.get("kind") == "retro_due"}
    check("S7>1d 出现提醒", "t1-retro2" in rt and rt["t1-retro2"]["severity"] == "normal")
    check("S7>7d 降级 stale", rt.get("t1-retro9", {}).get("severity") == "stale")
    check("S7 当天不出提醒", "t1-retro0" not in rt)
    check("S7 closed 不提醒", "t1-retro-closed" not in rt)
    # S6 标（非 S7）不产生复盘项
    _mk_bid("t1-s6", stage="S6")
    check("S6 不出复盘项", not any(i.get("kind") == "retro_due" and i.get("bid_id") == "t1-s6" for i in _now_items()))
    # DEV-0084 回归：进过 S7 但已离开（→S8）的标，提醒必须自消（原实现只查「进过 S7」永久滞留）
    _mk_bid("t1-retro-left")
    _backdate_s7("t1-retro-left", 3)
    store.set_stage("t1-retro-left", "S8", "S7", None, 0)
    check("离开 S7 提醒自消", not any(i.get("kind") == "retro_due" and i.get("bid_id") == "t1-retro-left" for i in _now_items()))

    # ⑥ 派生项与既有三类共存（工单/门禁失败/alerts 不受影响）
    kinds = {i.get("kind") for i in _now_items()}
    check("ticket 项仍在", "ticket" in kinds)

    # 清场（密封目录，礼貌关闭连接后删除）
    store._conn().close()
    shutil.rmtree(_TMP, ignore_errors=True)

    bad = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        print(f"  {'✅' if ok else '⛔'} {name}" + (f" — {detail}" if detail and not ok else ""))
    print(f"\n{'='*40}\nstore read_now 测试：{len(RESULTS) - len(bad)}/{len(RESULTS)} 通过")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
