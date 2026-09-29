#!/usr/bin/env python3
"""test_digest_cloud.py · R5 digest 云脱敏测试（T4 · DEV-0077）

密封 BIDMASTER_HOME（tempfile），全程不碰真实数据面。
覆盖：compute_stats 排除 classified 聚合 + classified_count 标量；_sanitize_cloud_stats
leads_p0_pending（buyer/title 名单）剔除换计数——存量 L3 修复的回归断言。
运行：python3 tests/test_digest_cloud.py；退出 0=全过。
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_TMP = tempfile.mkdtemp(prefix="bidmaster-t4-")
os.environ["BIDMASTER_HOME"] = _TMP  # 先于任何 app/store 导入
sys.path.insert(0, str(REPO / "rules"))
sys.path.insert(0, str(REPO))

import store  # noqa: E402
store.init()

from app.store import app_db  # noqa: E402
app_db.init()  # 含 leads.provenance 列迁移（T3）——顺带回归验证

from app.services import bid_service  # noqa: E402
from app.services import digest_service  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


def main() -> int:
    today = date.today().isoformat()
    # 夹具：1 个 real 标（行业/金额可聚合）+ 1 个 classified 壳（同行业不同金额）+ 1 个 demo
    bid_service.create({"code": "2026-t4-real", "client": "测试银行", "industry": "银行",
                        "region": "深圳", "est_amount": 280, "priority": "P0",
                        "due_at": f"{today} 17:00"})
    bid_service.create({"code": "2026-t4-shell", "client": "别名壳", "industry": "涉密行业X",
                        "region": "涉密区域Y", "est_amount": 9999, "priority": "P0",
                        "kind": "classified", "stage": "S5", "due_at": f"{today} 09:00"})
    bid_service.create({"code": "2026-t4-demo-x", "client": "演示", "industry": "演示行业"})

    # ① 全量 stats（本地口径）：壳参与聚合 + classified_count 标量在场
    full = digest_service.compute_stats(today)
    check("全量 by_industry 含壳行业", "涉密行业X" in (full.get("bids_by_industry") or {}))
    check("全量 classified_count=1", full.get("classified_count") == 1, str(full.get("classified_count")))
    check("全量 bids_total=3（real+壳+demo）", full.get("bids_total") == 3, str(full.get("bids_total")))

    # ② 云版 stats（exclude_classified）：壳从全部聚合消失，classified_count 保留
    cloud_raw = digest_service.compute_stats(today, exclude_classified=True)
    check("云版 by_industry 无壳行业", "涉密行业X" not in (cloud_raw.get("bids_by_industry") or {}))
    check("云版 by_region 无壳区域", "涉密区域Y" not in (cloud_raw.get("bids_by_region") or {}))
    check("云版 amount_sum 不含壳金额（防单壳反推）", cloud_raw.get("bids_amount_sum") == 280,
          str(cloud_raw.get("bids_amount_sum")))
    check("云版 classified_count=1（只知几单不知细节）", cloud_raw.get("classified_count") == 1)
    check("云版 bids_total=2", cloud_raw.get("bids_total") == 2)

    # ③ _sanitize_cloud_stats：leads buyer/title 名单剔除换计数（存量 L3 修复）
    stats_with_leads = dict(cloud_raw)
    stats_with_leads["leads_p0_pending"] = [{"title": "某涉密项目名称", "buyer": "某真实客户名", "score": 95}]
    cloud = digest_service._sanitize_cloud_stats(stats_with_leads)
    check("云 payload 无 leads_p0_pending 名单", "leads_p0_pending" not in cloud)
    check("云 payload 留 pending 计数", cloud.get("leads_p0_pending_count") == 1)
    blob = json.dumps(cloud, ensure_ascii=False)
    check("云 payload 序列化不含 buyer/title 字样", "某真实客户名" not in blob and "某涉密项目名称" not in blob)

    # ④ 本地渲染不受影响：_render 仍可用全量 stats（含 pending 明细列表时不出错）
    md = digest_service._render(full)
    check("本地 markdown 渲染含业务数据节", "业务数据" in md)

    # 清场（显式三条 DELETE——测试代码同样遵守静态 SQL 纪律）
    c = store._conn()
    with c:
        c.execute("DELETE FROM bid_profile WHERE bid_id LIKE '2026-t4-%'")
        c.execute("DELETE FROM stage_history WHERE bid_id LIKE '2026-t4-%'")
        c.execute("DELETE FROM bids WHERE bid_id LIKE '2026-t4-%'")
    store._conn().close()
    shutil.rmtree(_TMP, ignore_errors=True)

    bad = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        print(f"  {'✅' if ok else '⛔'} {name}" + (f" — {detail}" if detail and not ok else ""))
    print(f"\n{'='*40}\ndigest 云脱敏测试：{len(RESULTS) - len(bad)}/{len(RESULTS)} 通过")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
