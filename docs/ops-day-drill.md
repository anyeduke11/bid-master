# 一天全链路演练 runbook（W4 4.6 · 需一个真实工作日执行）

> 前置：owner 已安装 docs/ops-cron.md 的 crontab；看板已启动（./start.sh）；演示标 2026-demo-w2b 与真实标 2026-GOLD-jishu 在数据面。
> 记录方式：每步截图/输出追加到 log/day-drill-<日期>.md（体验报告素材，自动产生）。

| 时刻 | 动作 | 预期 | 采集 |
|---|---|---|---|
| 08:30 | cron consistency 自动跑 | alerts.json 更新（consistency.py 为占位时记录日志） | log/cron-*.log |
| 09:00 | cron digest | ~/.bidmaster/digests 出当日 stats | 同上 |
| 09:30 | 投放 3 条合成标讯到 leads/raw（或等 10:00 抓取） | — | — |
| 10:05 | bid-scout 打分（工单启动） | scored.jsonl 三分类+evidence | scout 回执 |
| 10:10 | validate_leads 机检 | 通过/拦截清单 | validate 输出 |
| 10:15 | 看板生成工单→复制→ZCode 开会话推进演示标 S4→S5 | 看板 5s 内感知 | /api/baw/bids 前后时间差 |
| 11:00 | bid-writer 扩写 1 章（真实标第 3 章）+ verify_draft | cite 违规=0 | verify 报告 |
| 14:00 | bid-auditor round-1 → 修复 → round-2 | 阻断单调下降 | audit-r1/r2 |
| 16:00 | 第二次抓取+scout | leads 增量去重 | leads.seen |
| 17:00 | S5→S6 演练（--sign-off） | 无签核拦截/签核放行 | set_stage.log |
| 22:00 | CronCreate queue-batch（隔夜批） | 工单 status→executed | queue/*.json |
| 次日 08:00 | 复盘：对照本表逐项打勾，缺口入 backlog | 体验报告 day-drill 章节 | log/day-drill-*.md |

**验收（M4）**：cron 醒着（log 有 08:30/09:00 记录）+ 事件生产（writer/auditor 产物）+ 看板消费（5s 感知复测）+ 工单闭环（generate→consumed）；`make regress` 出基线对比表。
