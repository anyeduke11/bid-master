# 周期任务编排（DEV-0081 重写：调度已迁服务内置）

> 原则：定时任务全部由 bid-master 自己承载（服务内置调度器）——不依赖 crontab/launchd，
> 换机/迁移/系统权限变化不再造成调度空心。服务起则调度在，服务停则调度停。
> 原设计依据（design §9 一天节奏）继续有效：周期性的醒着=脚本，事件性的聪明=ZCode，人在审批位。

## 现行机制（2026-09-26 起）

- **入口**：`./start.sh start`（一键启动看板服务，调度随服务启动）
- **节拍**：每 3 小时一轮（环境变量 `BIDMASTER_SCHED_INTERVAL` 秒可覆盖；<=0 禁用）；首轮在服务启动 30s 后
- **轮内任务（串行）**：capture 抓取 → qualify 评分 → scout 机检转正 → lead 状态复核（5 态）→ ingest 外部收割（只收 tender/lead-table）→ consistency 一致性 → digest 保底统计 → backup 数据库备份（**每周 cadence**，B1.4：truth.db+app.db+ingest registry，4 份滚动 + sha256 清单；手动触发强制跑）
- **观测**：
  - `GET /api/v1/scheduler`——状态/上一轮结果/下一轮时间
  - `POST /api/v1/scheduler/run`——手动触发一轮（与自动轮次互斥）
  - 日志：`~/.bidmaster/log/sched-<task>.log`（每轮覆写，保留最近一轮）
  - 事件流：type=sched_round（events 表 + log.jsonl + SSE 广播三通道）
- **手动单任务**：直接跑 rules/ 或 scripts/ 下对应脚本（cron_baw.sh 已加迁移闸门停用，见下）
- **当日必办类不自动化**（沿用原设计）：scout 打分、阶段推进、S5→S6 签核、工单启动——人工复制工单 / 看板按钮（人=审批位）

## 旧机制清退记录（2026-09-26，两阶段）

- launchd 6 项已 bootout，plist 归档 `~/.bidmaster/backup/launchd-plists-20260926/`（源在 rules/launchd/ 留存）
- crontab 已**物理删除**（DEV-0082，owner 授权后 `crontab -r` 成功；首轮挂 TCC 授权弹窗，二次执行放行）；
  备份 `~/.bidmaster/backup/crontab-20260926-pre-inapp-sched.txt`（8 行），`crontab -l` 现返回 "no crontab for duke"
- 迁移闸门标记 `~/.bidmaster/.sched-migrated` 已随删除同步移除——cron_baw.sh 手动入口恢复
  （`bash rules/cron_baw.sh digest` 实测正常）；系统级调度已 100% 清退

## 历史版本

- W4 4.3（2026-09 初）：crontab + cron_baw.sh 统一入口（后被 TCC 拦截读 Documents）
- DEV-0052（2026-09-15）：迁 launchd 用户代理 6 项（crontab 未拆，双轨并存 11 天）
- DEV-0081（2026-09-26）：服务内置调度器，系统级调度全数清退（crontab 条目暂由闸门中和）
- DEV-0082（2026-09-26）：owner 授权后 crontab 物理删除 + 闸门标记移除，系统级调度 100% 清退
