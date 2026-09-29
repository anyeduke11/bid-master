# bid-master 运行纪律（跨智能体 · 单角色细节见 skills/<role>/SKILL.md）

1. 唯一事实源在 `~/.bidmaster/truth.db`（真实层，v0.5.0 起）：一切状态/登记写入只走 `rules/store.py`（参数绑定 SQL）；`memory/bids.jsonl` 仅为兼容导出（勿直写）；线索暂存仅 bid-scout 写；`bids/<id>/` 生产层文件写后必须 `store.register_artifact` 登记；`kb/` 仅 apply_archive+人工确认后写。旧 bid-master skill 已退役（`~/.agents/skills/_retired-bid-master`），禁止按其旧协议直写数据面。
2. 外部工具目录（lingxi-claw / WorkBuddy / Trae）**只读收割，永不写入**。
3. L3 红线（成本价/折扣/客户名单/证件号/证书编号）不进任何 prompt、不落任何产物；客户一律别名+行业。
4. 产物须带 `"status":"final"` 才被看板消费；每次产物附 run manifest（producer/model/指纹/ticket_id/自检结果）。
5. 同一 bid 同时只开一个会话；状态推进只走 `rules/set_stage.py`（S5→S6 须 `--sign-off` 人工签核）。
6. 开工先读对应 `skills/<role>/SKILL.md` 与 `memory/lessons.md`；工单执行须回填 ticket_id。
7. 仓库内文件只保留最新版本：历史演进靠 git 机制管理，禁止在工作区堆 .bak/日期副本（gate 已拦，owner 定 2026-09-10）。
8. 消歧（注入优先级）：本文件为最高运行纪律——**只读智能体（locator/auditor）豁免全局 AGENTS.md 的 DEV_LOG 写入义务**，其"零文件写入"铁律优先；DEV_LOG 由主会话统一记录。

9. Mimosa 安全钩子协作协议（owner 2026-09-13 定）：
   9.1 优先走 Write/Edit：所有源码/配置变更优先用标准写入工具，让 hook 扫描。真问题会被拦住，这是 hook 的价值。
   9.2 误报三元组记录：被拦且人工核对后确认为误报时，记录三要素到 DEV_LOG.md（文件路径+行号、hook 报错类型、人工核对结论）。
   9.3 旁路落地必须可追溯：python 旁路写入（shutil.copy / subprocess 调用外部脚本）只用于已确认误报的代码，且旁路落地后立即在 DEV_LOG 补一条记录。不允许静默旁路。
   9.4 定期反馈上游：误报样本积累到 5 条或同一模式出现 3 次，由 owner 反馈给 Mimosa 团队（issue/邮件）。这是唯一能真正降噪的路径。
   9.5 安全底线不变：Mimosa 误报不豁免安全审查。参数化 SQL / SSRF 防护 / L3 红线仍严格执行，只是应对误报的流程纪律。

10. Karpathy 四原则（行为纪律，2026-09-18 自 Git4GenThinking ch02 采纳；源 https://github.com/multica-ai/andrej-karpathy-skills）：
    先思考（不确定就问，有更简单的方法就说出来）→ 简单优先 → 精准修改（只改必须改的）→ 目标驱动（明确目标再动手）。
    与第 9 条 Mimosa 协议并行生效：优先 Write/Edit、误报台账、旁路留痕等流程纪律不因本条简化。
