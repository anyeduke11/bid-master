# BAW 实施计划（4 周 · 2026-09-14 起）

> **产品版本：v0.4.0（BAW 阶段首版，2026-09-10 W4 收口）**
> 依据：`docs/baw-design-v3.md` / `docs/prd-baw-v6.md` / `docs/acceptance-agents.md`
> 投入假设：每周 8–10 小时，共 35–40 小时
| 里程碑优先级 M1 > M2 > M3 > M4；M1+M2 达成即具备体验报告最低提交条件

> **执行进度（2026-09-10 更新）**：W1 ✅（提前完成）→ W2 ✅（数据面 + kanban v0.4，M2 达成）→ W3 ✅（3.1/3.2/3.3/3.5/3.6，M3 五项达成）→ **W4 ✅（4.1–4.7，本日收口）**。遗留项统一收口 `docs/backlog.md`。

---

## 0. 前置依赖（开工首日核对）

- [ ] Shell 故障已恢复（本设计会话期间 /bin/zsh 持续 ENOENT，开工前先修复）
- [x] 外部目录已现场复核（2026-09-10）：`~/Documents/lingxi-claw/` 225 个批次，命名混杂（时间戳 / weixin- 前缀 / 散落 md 文件）→ ingest 类型识别需按内容而非目录名；`~/WorkBuddy/Claw/` 99 个 xlsx；`~/WorkBuddy/bid-agent-workbench/` **不存在**
- [x] 目录改名 bid-board→bid-master 已完成（2026-09-10），仅剩随迁核对（见 1.1）
- [ ] ZCode 环境可用（Bigmodel 授权、推理强度最高、计划模式）

## 1. W1 地基周（~~09-14 ~ 09-20~~ ✅ 2026-09-10 提前完成）

| # | 任务 | 交付物 |
|---|---|---|
| 1.1 | **目录重定向（改名已完成，本项只剩随迁核对）**：核对 `.zcode/agents/bid-scout.md` 已随目录走（✅已确认）/ start.sh 相对路径不受影响 / README 旧路径 `~/.minimax-agent-cn` 修正 / 清理 7 个 server.py.bak | `./start.sh` 起服务正常，README 路径正确 |
| 1.2 | **Git 纳管**：从 `/Users/duke` 大仓库中独立建仓；`.gitignore` 排除 `~/.bidmaster/`、`~/.bidboard/`、`*.bak`；首次 commit | 独立仓库，pre-commit 挂 `make gate` |
| 1.3 | **workbench 结构落位**：建立 `agents/ skills/ rules/ tests/golden/ kb/{index,raw,slices} out/ log/ runs/ queue/ inbox/` 骨架（`~/WorkBuddy/bid-agent-workbench/` 经核实不存在，直接新建） | 目录骨架 + README 名字映射表（目录/skill/数据目录三义性说明） |
| 1.4 | **W1 实测 6 项**（见 §5） | 实测记录 `log/w1-verify.md` |
| 1.5 | **金标准初始化**：金标准演练标（有完整投标文件）人工标注全部★项与评分点 → `tests/golden/` | 金标准 v1 |
| 1.6 | Memory 更新：持久记忆中 bid-board 路径改为 bid-master | 记忆一致 |

**M1 验收**：仓库独立且 gate 可跑；实测 6 项有结论（不满足的启用 fallback）；金标准 v1 交付。

> **W1 执行注记（2026-09-10 提前完成，`log/w1-verify.md`）**——遗留待 owner：
> - [ ] 金标准人工确认（对照原始 PDF，star-items/scoring-points draft→confirmed）→ 升 v1
> - [ ] 重启会话后复测 w1-readonly-probe（tools 强制定论），测后删探针
> - [x] ~~duke-portfolio/ 是否继续纳管~~ → **已决（2026-09-10）：纳管，只保留最新版本**。核实：该目录历史仅 1 个版本（02c7fa0 快照）且与 HEAD 一致，无需重写；后续按 AGENTS.md 第 7 条纪律执行（工作区不留多版本副本）

## 2. W2 状态机与数据面（原 09-21 ~ 09-27 → 实际自 2026-09-10 起）

> W1 实测对 W2 的输入：①新 agent 需重启会话注册（冒烟前先重启）；②tools 强制定论取决于探针复测——本周期脚本机检是只读边界的实际兜底；③CronCreate 自动消费仅限批处理类（当日任务人工）。

| # | 任务 | 交付物 | 状态 |
|---|---|---|---|
| 2.1 | **set-stage 门禁内嵌**：S0–S9 + §8.2 门禁矩阵全部实现为脚本校验 | `rules/set_stage.py`（`bid.advance_stage` 的唯一实现，看板/CLI/会话同调）；拒绝返回卡点清单 | 开发中 |
| 2.2 | **watcher 完稿标记协议**：只认 `status=final`；投影缓存 rebuild 命令 | `docs/data-plane-protocol.md` + `rules/rebuild_cache.py` → `make rebuild-cache` | 开发中 |
| 2.3 | **kb 骨架与 index 初始化**：certs/people/cases 从现有资产（三标+历史投标）录 index；raw 归档 | `rules/kb_init.py` 半自动 → `kb/index/*.json` v1（draft 待人工复核） | 开发中 |
| 2.4 | **desensitize.py**：正则模式库（身份证/手机/证书编号）+ 挂 inbox→转正路径 + 自测样本 | `rules/desensitize.py`（并挂 S8→S9 门禁）+ `tests/sample/desensitize/` | 开发中 |
| 2.5 | set-stage 校验耗时实测；超 2s 则加 stage 元数据缓存 | 性能达标（--timing 输出） | 开发中 |
| 2.6 | **项目级 AGENTS.md**：新建 `bid-master/AGENTS.md`——只放跨智能体运行纪律（≤10 行）：数据面在 `~/.bidmaster`（单一写者）、脱敏红线、ticket_id 回填、只读边界声明；单角色细节仍归各 SKILL.md 不上提。落地后逐个评估开启 5 个智能体的"注入 AGENTS.md"（一处更新全员生效） | `bid-master/AGENTS.md` v1 + 注入开关决策记录 | 开发中 |

**M2 验收**：一标从 S3 推进到 S6 的全链路演示——门禁拦截与放行各一次、卡点显示正确、看板 5s 内感知。
> **✅ 2026-09-10 达成**：数据面 16 步演示（`log/w2-demo.md` §一）+ kanban v0.4 联调 9 点全绿（`log/w2-demo.md` §六：感知延迟实测 2.1s ≤5s；HTTP 拦/放各一；卡点正确；update_field stage 拦截）。W2 全部任务完成。

## 3. W3 生产链路（原 09-28 ~ 10-04 → 实际约 09-17 ~，国庆弹性保留）

> **✅ 2026-09-10 单日完成 3.1/3.2/3.3/3.5/3.6 全部五项**（3.4 前期已关）：
> - 3.1 ✅ 规则库 48 条（`rules/audit/audit-rules.json`，bid-file-review+BD-0025+某证券通信机构实证，金标准同源）
> - 3.2 ✅ verify_draft.py 四项机检 + 自测（cite 违规=0/覆盖/字数/manifest）
> - 3.3 ✅ ticket.py 三命令 + 模板×5，工单闭环（generate→对账消单实测）
> - 3.5 ✅ 对抗闭环演练（真实金标准演练标 2 章：双 writer 并行→机检双 PASS→auditor r1 一般 5→修复→r2 清零收敛；含"审计修复撞字数上限"真实返工，`log/w3-drill.md`）
> - 3.6 ✅（首梳）教训链索引：10 条无取代、procedural 不衰减
>
> **M3 验收**：端到端跑通 ✅；writer cite 违规=0 ✅；auditor 注入检出 ≥8/10 🟡（合成样本预检 9/10，正式注入集待对真实产物建——W4 4.5 一并）。

| # | 任务 | 交付物 |
|---|---|---|
| 3.1 | **audit 规则库抽取**：bid-file-review 检查表拆解为 `rules/audit/`（auditor 弹药库；源=v2.5 SKILL + `references/tender_audit_checklist.md` + 某证券通信机构核对单实证，**金标准评测同源**）；bid-file-review 标记 deprecated 归档 | audit 规则库 v1 |
| 3.2 | **writer 契约与机检**：规格单 schema + `verify_draft.py`（cite 白名单/评分点覆盖/字数区间） | writer 可验收 |
| 3.3 | **工单机制**：模板库 5 个 + `ticket.generate/list` 命令 + queue/ 存档 + ticket_id 闭环对账 | 工单闭环演示 |
| 3.4 | **agent 定义落盘**：bid-writer / bid-locator / bid-auditor / bid-archivist 四个 .md（含"开工先 Read SKILL.md"绑定）——**2026-09-10 已完成并冒烟通过**（owner UI 创建落盘 + frontmatter 补正 + 5 个 SKILL.md v0 + 7 项冒烟全过，见 `log/agent-smoke.md`；auditor 金标准预检 9/10 ≥8 达标；tools 只读约束实测成立）。**本项关闭** | 4 个角色包 ✅ |
| 3.5 | **对抗闭环演练**：选一标真实跑 分工写作制 2 章 + auditor round-1→修复→round-2 | 演练记录（含失败与返工，如实） |
| 3.6 | **存量教训补结构化（自 W4 4.4 前移，owner 定 2026-09-10）**：教训 ID 化已完成（L-1~L-10 迁入 BAW 格式）；本项完成 supersession 链梳理、衰减标注、skill 时代新教训并轨 | lessons.md 全量结构化 |

**M3 验收**：分工写作制端到端跑通（规格单→writer 扩写→机检→审计→修复）；writer cite 违规=0；auditor 金标准注入检出≥8/10（对照 acceptance §3）。

## 4. W4 采集与飞轮（原 10-05 ~ 10-18 弹性 → **✅ 2026-09-10 当日收口**）

| # | 任务 | 交付物 | 状态 |
|---|---|---|---|
| 4.1 | **采集链路**：lead_capture 移植 + bid-scout 升级契约版 + `validate_leads.py` | 商机视图活数据（`~/.bidmaster/leads/`） | ✅ 移植+机检（自测过） |
| 4.2 | **收割上线**：ingest.py（flock + 幂等指纹 + 类型识别）+ cron 扫 lingxi-claw/WorkBuddy 增量 | inbox 链路 | ✅（dry-run 验证；首次全量待 owner 确认→backlog A5） |
| 4.3 | **cron 编排错峰**：08:30 consistency / 09:00 digest / 10:00+16:00 抓取+scout | crontab + CronCreate 清单 | ✅ 清单就绪（`docs/ops-cron.md`；装机待 owner→A2） |
| 4.4 | **归档飞轮**：apply_archive（幂等）+ lessons 采纳确认（结构化前移 W3 3.6 已完成） | S8→S9 门禁完整 | ✅ 幂等双跑实测（no-op + kb 去重） |
| 4.5 | **A/B 度量 + 回归固化**：同材料双跑计时计数；`make regress` 基线入 Git | 度量表 8 项填实 | ✅ 首份基线 `runs/baseline-20260910-w3.json` 入 Git，6 指标全绿 |
| 4.6 | 全链路一天演练 + 体验报告素材整理（自动产生，不补记） | M4 报告 | 🟡 素材已汇编（`out/report/experience-report-material.md`）+ runbook（`docs/ops-day-drill.md`）；实际一天演练需 A2/A3 配合 |
| 4.7 | **收尾动作**：Mimosa 深度扫描（deep，重点=各功能间逻辑与调用关系）+ 遗留处置清单 | 扫描报告归档 `out/` | ✅ 已跑（scanId 在案，findingCount=0，seal 密封；覆盖不完整提示照录→backlog C2） |

**M4 验收**：一天演练全通（cron 醒着 + 事件生产 + 看板消费 + 工单闭环）；`make regress` 输出基线对比表。
> 🟡 `make regress` 对比表已出（首份基线 6 指标全绿）；"一天演练"runbook 就绪、待真实工作日执行（A2/A3）——M4 差这一步实跑。

## 5. W1 实测清单（6 项，含 fallback）

| # | 实测项 | 通过标准 | 不通过时 fallback |
|---|---|---|---|
| 1 | agent frontmatter `tools:` 字段只读强制 | auditor/locator 无法写文件 | git diff 防护目录 + 机检兜底 |
| 2 | 异档模型去相关（GLM-5.3 vs Flash） | 同 10 条已知缺陷检出差异≥2 条 | 接受部分去相关，人工抽检加密 |
| 3 | run_in_background 并行（locator∥auditor）汇合 | 两结果可收集、时序无竞争 | 串行执行（效率损失可接受） |
| 4 | 子智能体内"开工先 Read SKILL.md" | 输出含契约结构（效果验证） | 关键工艺冗余进 agent .md |
| 5 | CronCreate 定时消费 queue/ | 定时任务读到工单并执行 | 纯人工复制（一期本就支持） |
| 6 | ZCode CLI 带 prompt 启动 | 工单可变一键启动命令 | 纯复制粘贴（机制不受损） |

## 6. 度量与报告（过程自动产生）

| 指标 | 口径 | 采集点 |
|---|---|---|
| 单标准备工时 | 拿到招标文件→可提交草稿 | 工单 ticket 时间戳差 |
| ★项召回率 | 对照金标准，100% 硬指标 | `make regress` |
| 定位准确率 | 抽样 20 条 | locator 报告 |
| 阻断级缺陷数 | 门禁检出 | gate/run manifest |
| 返工量 | 修改处数+字数 | git diff |
| 契约符合率 | agent 产物 schema 通过率 | run manifest 统计 |
| token 成本 | 每标消耗 | run manifest |
| 中标率 | 长期观察，不承诺 | — |

## 7. 风险应对（摘自设计 §15，周度检查）

- P0 ZCode 不可用 → 全路径无 LLM 降级已设计，W3 演练一次降级切换
- P0 子智能体产出不可信 → 主 Agent 重跑校验，双保险已设计
- P1 改名迁移断裂 → W1 迁移清单逐项核对
- P1 PDF 表格丢失 → 单章验证 + OCR + source=secondary 标记
- P2 时间不足 → 砍 M4 保 M1+M2
