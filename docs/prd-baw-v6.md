# PRD v6.0 — bid-master 跟踪看板（BAW 门面层）

> 版本：v6.0（2026-09-10）· 承接 PRD v5.2 终稿（v0.3.2 产品）之上的 BAW 重设计基线
> 设计依据：`docs/baw-design-v3.md`
> 产品版本映射：本 PRD 对应产品 v0.4.0（BAW 阶段首版）

---

## 1. 产品定位

> **Duke 的投标全生命周期工作看板：数据消费与展示 + 人的审批入口 + 生产工单发生器。**

三条不可违反的产品宪法：
1. **不拥有业务状态**——唯一事实源在 `~/.bidmaster/`（文件），看板 SQLite 只是可随时重建的投影缓存；
2. **不直接指挥 ZCode**——任务衔接靠提示词工单（人复制启动）；
3. **不生产语义**——语义生产全部在 ZCode 侧；看板只跑确定性脚本。

## 2. 用户与场景

单用户（Duke，本机），三类日常场景：
- **晨间巡检（5 分钟）**：今日必办 → digest → 商机新线索处理
- **盘中操作（事件驱动）**：单标深潜看进度/缺陷 → 生成工单去 ZCode 干活 → 回来看板消单
- **阶段签核（低频高危）**：S5→S6 封标放行等 L3 审批

## 3. 视图需求（7 视图）

| 视图 | 内容 | 关键交互 |
|---|---|---|
| 📊 管线漏斗 | S0–S9 各态标的数+金额+停留时长；卡片按 P0/P1/P2 | 点卡片进深潜；卡点标红（门禁未过原因） |
| 🔍 单标深潜 | 阶段进度条 / 废标风险数 / 缺陷面板（auditor 轮次）/ 素材引用反查 / timeline 倒计时 / per-bid dashboard.html 内嵌入口 | 生成工单按钮；阶段推进按钮（走 set-stage） |
| ☀️ 今日必办 | 截止倒计时+待审批+阻断级缺陷+证照到期+人员跨标冲突+素材缺口（alerts.json + consistency 产出） | 逐条处理/忽略（留痕） |
| 🗂 资产台账 | certs/people/cases/solutions 四域清单+到期预警+在投占用 | 只读+筛选；缺口登记 |
| 📥 商机 | lead 池（scout 打分+evidence）、validate 拒绝队列 | lead 升级为正式 bid（L3 人工） |
| 📰 digest | 日/周报（digest_stats 脚本保底，LLM 增强可选） | 导出 md |
| ⚙️ 系统 | agent 名册（模型/版本/最近运行/校验通过率）/ skill 版本与 golden 基线 / 规则变更史 / kb 体检（各域条数/过期）/ 工单队列与状态 / 运行日志 | 参数配置；内容提案流；手动触发脚本类生产 |

## 4. 命令注册表扩展（在现有 11 命令基础上）

| 新命令 | 类型 | 幂等 | 说明 |
|---|---|---|---|
| `bid.advance_stage` | gate | ✅ | 调 set-stage（门禁内嵌）；拒绝时返回卡点清单 |
| `ticket.generate` | platform | ✅ | 按模板+活数据生成工单，写 queue/ 并返回可复制文本 |
| `ticket.list` | query | — | 工单状态（生成/已执行/已消单） |
| `kb.stats` / `kb.query` | query | — | 资产台账数据源 |
| `inbox.ingest` | platform | ✅ | 手动触发收割（flock 防并发） |
| `config.update` | platform | ✅ | **参数级配置**（阈值/渠道开关/cron 时刻/画像参数 → config.json） |
| `proposal.submit` / `proposal.apply` | platform | ✅ | **内容级配置提案流**（agent prompt/skill 工艺/工单模板编辑 → .pending → validator → 人确认 → git commit） |

保留既有命令（bid.create / lead.promote / playbook.run 等），`bid.update_field` 中 stage 字段写操作改为强制走 `bid.advance_stage`。

## 5. 数据需求

| 数据源 | 方式 | 频率 |
|---|---|---|
| `~/.bidmaster/bids/*/data/*.json` | watcher 轮询（只认 status=final） | 5s |
| `~/.bidmaster/memory/bids.jsonl / certs.json` | watcher | 5s |
| `~/.bidmaster/inbox/ / queue/ / alerts.json / digests/` | watcher | 5s |
| `.zcode/agents/ *.md、skills/*/SKILL.md、rules/*` | watcher（系统视图） | 5s |
| run manifest（runs/） | watcher | 5s |

投影缓存重建命令：`make rebuild-cache`（从文件全量重建看板库，作为投影层故障恢复手段与"看板不拥有状态"的证明）。

## 6. 配置能力三级（可行性结论）

| 级别 | 能力 | 方式 |
|---|---|---|
| 参数级 | 阈值/渠道/cron/画像 | 直接写 config.json ✅ |
| 内容级 | agent prompt / skill 工艺 / 工单模板 | 提案流：编辑→.pending.md→validator→人确认→git commit。**禁止热改生效中的 prompt**（保 golden 基线） |
| 触发级 | 看板按钮拉起 ZCode 会话 | 一期 ❌（ZCode 无对外 API）→ 工单复制衔接；二期 CronCreate 消费 queue |

## 7. 工单功能（Prompt Ticket）

- 模板库（进 Git 版本化）：新标分析 / 审计 round-N / 归档收割 / kb 初始化 / queue 批处理
- 变量自动填充：bid_id、当前 stage、缺陷计数、文件路径、待读 lessons 条目号
- 工单必含：任务目标 / 输入路径 / 开工必读 / 工艺路径 / **完成条件（=门禁清单原文）** / ticket_id 回填要求
- 状态流转：生成 →（人复制，不追踪）→ 已执行（产物 run manifest 带 ticket_id）→ 已消单（watcher 对账）
- 纪律：给路径和目标，不内嵌大段内容

## 8. 非功能需求

| 项 | 要求 |
|---|---|
| watcher 感知延迟 | ≤ 5s |
| 命令响应 | ≤ 2s（门禁校验串行超时则缓存进 bids.jsonl stage 元数据） |
| 幂等 | 全部新命令带 Idempotency-Key + Payload-Hash（沿用既有机制） |
| 审计 | 命令/审批/提案/消单全留痕（log.jsonl） |
| 脱敏 | inbox→转正路径 100% 过 desensitate 正则库，命中即拦 |
| 单写者 | 看板库仅 watcher 与命令处理器写入；可随时 rebuild |
| 兼容 | 沿用 :8080、start.sh、既有 7 视图框架渐进改造 |

## 9. 里程碑与验收对照

| 里程碑 | 看板侧交付 | 验收（对照 acceptance-agents.md） |
|---|---|---|
| M2 | set-stage 门禁命令 + watcher 完稿标记 + 投影缓存 rebuild | 一标 S3→S6 推进演示：被拦/放行各一次，卡点显示正确 |
| M3 | 工单生成/消单 + 系统视图（agent/skill 名册） + 缺陷面板 | 工单闭环（ticket_id 对账）演示 |
| M4 | 商机视图（scout 打分）+ digest + 今日必办（alerts/consistency） + inbox 手动收割 | 全链路一天演练 |

## 10. 明确不做的事

- 不做直接拉起 ZCode（一期）
- 不做 RAG / 向量检索 / 知识图谱
- 不做多用户与远程鉴权（单用户本机；ADMIN_TOKEN 模式保留）
- 不动 bid-news-kanban 与外部工具目录（只读收割）
- 不做合同/交付/回款经营段（二期，迁移 kanban 闭环）
- 不做移动端/飞书 Bot（远期观察项）
