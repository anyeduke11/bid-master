# BAW v3.0 设计方案 — 投标智能体工作台（Bid Agent Workbench）

> 版本：v3.0（2026-09-10 定稿）
> 状态：已确认，待实施（目录改名 bid-board→bid-master 已于 2026-09-10 完成；前置：W1 独立建仓）
> 取代：`~/WorkBuddy/每周AI复盘/方案-投标智能体工作台ZCode体验-v2.0-20260909.md`（其 W1 执行细节仍有效，系统层设计以本文档为准）
> 配套文档：`docs/prd-baw-v6.md`（产品需求）、`docs/plan-baw-implementation.md`（实施计划）、`docs/acceptance-agents.md`（智能体验收标准）

---

## 1. 目标与定位

**主目标**：解决方案专家（Duke）日常办公的重要工作看板——从标讯线索到复盘归档的全生命周期生产与跟踪系统。

**副产物**：ZCode 体验报告素材（交互日志、回归对比、A/B 度量、成本表）在执行过程中自动产生，不做事后补记。

**一句话架构**：**kanban 是电网，ZCode 是峰值发电机，skill 是工艺手册，gate 是安全带，人在审批位，飞轮是护城河。**

诚实边界：一个月内可验证工时/召回率/返工率/缺陷数/token 成本；**中标率列为长期观察指标，不承诺**。

---

## 2. 决策记录（D1–D13，全部已确认）

| # | 决策 | 要点 |
|---|---|---|
| D1 | bid-news-kanban 冻结不动 | 能力迁移到 bid-master 项目，kanban 作为规格参考库（PRD/AGENT_API），活跃标的数据可一次性导出 |
| D2 | 生产底座 = ZCode 子智能体 + skill | 语义生产在 ZCode 会话；确定性在 skill 内脚本；ZCode 不在场时生产暂停但跟踪看板靠 watcher+cron 照常运转 |
| D3 | bid-master = 跟踪看板 | 数据消费与展示 + 人的审批入口；**不拥有业务状态**（投影缓存可重建） |
| D4 | bid-board 目录改名 bid-master（**已执行 2026-09-10**） | 承接 workbench 结构（agents/skills/rules/tests/kb/out/log）；设计文档位于 `bid-master/docs/` |
| D5 | bid-master skill 整合 bid-file-review | 评审方检查表拆解为 auditor 弹药库 + gate 清单；bid-file-review 标记 deprecated 归档 |
| D6 | 子智能体收敛为 5 个 | scout / writer / locator / auditor / archivist（v2.0 的 go-no-go/decon/responder/pricer 并入 bid-master 主链路阶段 0–2） |
| D7 | 语义主链路单上下文铁律 | 解构/关键件/价格模型由主 Agent 单任务连续上下文完成，禁止派生子代理做语义解析（三标验证教训：上下文割裂=定位断裂） |
| D8 | 生命周期 = S0–S9 状态机 | set-stage 为唯一状态写入口，门禁逻辑内嵌其中 |
| D9 | kb 采用 llm-wiki-2.0 生命周期思想 | 采纳 crystallization / supersession / 摄取口脱敏 / 衰减；不采纳知识图谱与多 agent mesh |
| D10 | 消费走指针，不走搜索 | 不做本地 RAG/向量检索；主 Agent 读分域小 JSON 做匹配，下游按指针精确取用 |
| D11 | 数据流编舞：周期=脚本，事件=ZCode | 两世界在"文件落盘"处交接，看板只认完稿标记 |
| D12 | 外部工具收割模式接入 | lingxi-claw / WorkBuddy / Trae 只读收割进 inbox，不动对方目录 |
| D13 | 提示词工单（Prompt Ticket） | 一期人肉复制传输（=天然人在环路审批位），二期 CronCreate 自动消费，工单格式不变 |

---

## 3. 系统架构

```
┌─ 生产底座（ZCode 会话 · 事件驱动）──────────────────────┐
│  主 Agent：语义主链路（解构→规格单→关键件→价格模型）      │
│  子智能体 ×5：scout / writer / locator / auditor / archivist │
│  Harness：Agent定义 + Skill工艺 + rules契约 + kb素材        │
│  脚本（确定性）：对账/渲染/状态推进/机检                    │
│  产物与状态：~/.bidmaster/bids/<bid_id>/ + memory/bids.jsonl │
└───────────────┬─────────────────────────────────────┘
                │ 单向：文件 → watcher(5s) → 看板投影缓存
                │ 审批/推进：看板命令 → set-stage（门禁内嵌）
                │ 任务衔接：工单（看板生成 → 人复制 → ZCode 执行）
┌─ 跟踪看板（bid-master 项目，原 bid-board，:8080）────────┐
│  视图：管线漏斗/单标深潜/今日必办/资产台账/商机/digest/系统 │
└──────────────────────────────────────────────┘
┌─ 冻结资产 ──────────────────────────────────────┐
│  bid-news-kanban（:7001，不动）；外部工具目录（只读收割）     │
└──────────────────────────────────────────────┘
```

---

## 4. 智能体编制

**设计法则（四问一档）**：①IO 边界能否写成文件契约？②输出能否被脚本机械校验？③是否依赖主链路连续上下文（依赖→主 Agent）？④失效有无无聊兜底？＋成本分档（高频轻任务 pin Flash，低频重任务主档/异构）。

**铁律**：脚本能做的不许做 Agent；渲染/对账/去重/状态推进全部是脚本。

| Agent | 定位 | 模型 | 权限 | 触发 | 频率 |
|---|---|---|---|---|---|
| 主 Agent | 语义主链路：五阶段分析 + 规格单 + 关键件撰写 | 主档（GLM-5.3） | 全 | 人开会话（工单启动） | 每标数次 |
| `bid-scout` | 标讯初筛打分 → 线索暂存区 | Flash | 读网+写暂存 | cron 跟抓取后/手动 | 每日 2 次 |
| `bid-writer` | 按规格单逐章扩写技术标正文 | 主档 | 读写 draft/ | 主 Agent 派发 | 编制期 |
| `bid-locator` | P0 条目二次定位抽查 | Flash | **只读** | 主 Agent（阶段产物落盘后） | 每阶段 |
| `bid-auditor` | 对抗审查（找茬不写作） | **Flash（owner 定版 2026-09-10）**；同家族去相关不成立（§13 实测 2），补偿=cite 机检+人工抽检加密 | **只读** | 阶段门 | 每标 2–3 轮 |
| `bid-archivist` | 归档提案（不直接写记忆库） | Flash | 读产物+写提案 | 开标后手动 | 每标 1 次 |

Agent 定义存放：`~/Documents/bid-master/.zcode/agents/`（项目级，随 Git 版本化）。

### 4.1 ZCode 智能体创建规范（2026-09-10 增补 · UI 手动创建）

完整逐字段参数与系统提示词全文见 `docs/zcode-agents-and-skills-plan.md`（owner 手动在 ZCode「新建子智能体」UI 创建，作用域 bid-master）。要点：

**UI 字段 ↔ frontmatter 映射**：名称→`name`（须与 .md 文件名一致）、颜色→`color`、模型→`model`（主档 `custom:builtin%3Abigmodel-coding-plan:GLM-5.3`，Flash `…GLM-5.3-Flash`）、描述→`description`、可用工具→`tools:`、系统提示词→正文、注入 AGENTS.md→`injectAgentsMd`。

**五智能体参数速查**：

| 名称 | 颜色 | 模型 | 可用工具 | 注入 AGENTS.md | 绑定 skill |
|---|---|---|---|---|---|
| `bid-writer` | 蓝 | 主档 | Read, Write, Edit, Glob, Grep（**无联网**） | 开（同上，实况） | skills/bid-write/ |
| `bid-locator` | 青 | Flash | Read, Glob, Grep | 开（同上，实况） | skills/bid-locate/ |
| `bid-auditor` | 红 | Flash | Read, Glob, Grep | **开（owner UI 定版实况；注入项目级 AGENTS.md 运行纪律）** | skills/bid-audit/ |
| `bid-archivist` | 绿 | Flash | Read, Write, Edit, Glob, Grep | 开（同上，实况） | skills/bid-archive/ |
| `bid-scout` | 黄 | Flash | Read, Write, Edit, Glob, Grep, WebSearch, WebFetch | 关（原为开，改） | skills/bid-scout/ |

**三条创建纪律（W1 实测约束内化）**：
1. **保存≠生效**：新 agent 需重启会话注册（w1-verify 实测 1）；创建后统一重启一次再冒烟。
2. **工具白名单按声明+防御纵深对待**：执行层强制未证实（实测 1 ⚠️）→ 只读边界 = 工具声明 + 提示词铁律（"即使有写能力也禁止使用"）+ rules 机检/git diff 兜底，三层缺一不可。
3. **所有提示词第一条 =「开工先 Read SKILL.md」**（实测 4 ✅ 契约有效），并带"读不到即停"失败语义。
4. **注入 AGENTS.md：owner UI 定版为开（2026-09-10 实况）**——项目级 `bid-master/AGENTS.md`（运行纪律）随创建注入，一处更新全员生效；全局/工作区 AGENTS.md 同时注入的噪声与义务冲突（全局"改码必写 DEV_LOG" vs 只读铁律）由项目 AGENTS.md 消歧条款解决（见 AGENTS.md 第 8 条）。
5. **提示词/skill 属内容级配置**：变更走提案流（.pending → validator → 人确认 → commit）+ `make regress`（golden 基线建立后），禁止热改生效中的定义（同 PRD §6 三级配置）。

skill 配套：5 个 SKILL.md 先落 v0（含降级路径：机检未上线时人工清单顶上、manifest 标注），W2/W3 机检脚本落地后升 v1（提案流 + `make regress`）。


---

## 5. 标书写作流水线（分工写作制）

**标书不是一个智能体写，是一条流水线**：

| 角色 | 写什么 | 占比 |
|---|---|---|
| 主 Agent（总撰稿） | ①《写作规格单》（每章：评分点+权重+原文引用[页码·逐字]+素材kb指针+字数+格式+禁止项）②"错一字即废标"关键件：投标函/商务偏离表/资质响应表/价格策略说明 | 篇幅 20%，风险 100% |
| `bid-writer` | 按规格单逐章扩写技术标正文（分章可 run_in_background 并行） | 篇幅 80%，模板性 |
| locator+auditor | 引用复核 + 对抗审查 | — |
| 脚本 | docx 渲染 | — |

**不违反语义铁律的原因**：writer 是按规格生成，不自己定位原文——所有招标文件引用由规格单预先锁定，writer 禁止新增招标文件断言，机检强制（cite 白名单：writer 输出中每个 [P#] 引用必须在规格单白名单内，违规=幻觉断言，整章打回）。

## 6. 知识资产层 kb

### 6.1 三层结构：「索引是契约，原件是证据，切片是耗材」

```
kb/
├── index/    certs.json / people.json / cases.json / solutions.json / bids_history.json
│             （分域小 JSON，主 Agent 可全读；每条含 file指针/fingerprint/敏感级/updated_at）
├── raw/      原件（certs/people/cases/solutions/past-bids，文件名规范化，永不改动）
└── slices/   切片（语义消费单元，frontmatter：来源/适用场景/敏感级）
```

### 6.2 ZCode 三种消费模式

| 模式 | 场景 | 执行者 |
|---|---|---|
| 元数据过滤 | 阶段 0 资质硬条件匹配 | 脚本 L1 机检（precheck_auto） |
| 规格单指针 | 阶段 4 编制，素材引用=切片路径#行号 | 主 Agent 写指针，writer 按指针读 |
| 归档回流 | 开标后新案例/方案入库 | archivist 提案 → apply_archive 应用 |

### 6.3 生命周期（llm-wiki-2.0 采纳项）

- **四层记忆映射**：working（单标工作产物）→ episodic（复盘归因）→ semantic（客户画像/教训库）→ procedural（检查规则/工艺）
- **supersession**：lessons.md 新教训必须写"取代了哪条旧教训"，防自相矛盾
- **衰减**：证照按有效期；案例带时效标签（金融客户只认近 3 年）；超 1 年未引用且被取代的教训标"沉淀"不删除
- **摄取口脱敏**：desensitize.py 正则扫描（身份证/手机/证书编号模式）挂在 inbox→转正路上，命中即拦

### 6.4 飞轮：门禁强制，不靠自觉

- **强制生产**：S8→S9 门禁要求已验证的 archive/proposal.json + lessons 采纳记录，否则状态机不推进
- **强制应用**：①开工必读 lessons/clients/certs（运行协议）+ 阶段 0 产物必含 lessons_applied 字段（S2→S3 门禁校验）；②规格单素材指针 + "评分点-素材匹配率"为 S4→S5 门禁前置；③资质硬条件机检

### 6.5 看板消费：资产台账 / 单标引用反查 / 素材缺口提示

存量初始化（W2 一次性）：lingxi-claw 三标产物 + 历史投标文件 → raw 归档 → 半自动填 index → 高复用方案类做切片（脚本切块+LLM 标适用场景+人抽检）；简历/资质类只建索引不切片。

## 7. Harness 与可观测性

### 7.1 角色包四件套绑定

```
agents/bid-writer.md          # 谁：定位/pin模型/三条铁律冗余
skills/bid-write/SKILL.md     # 怎么干：工艺流程+自检清单（agent prompt 第一条写死"开工先 Read 本文件"）
rules/writer_contract.json    # 什么算合格：输出 schema + cite 白名单校验脚本
kb/slices/…                   # 用什么料：规格单指针
```

skill 重组为分层工具箱：bid-master SKILL.md 是主 Agent 五阶段流程书；可共享脚本（extract_source/render/verify/memory）抽为公共工具箱。

### 7.2 可观测性三原则（第一性修正，反对理想化）

1. **信任零假设**：子智能体产出=不可信输入；唯一保险丝是主 Agent 收到后**重跑校验**（verify-after-return）；子智能体自检仅是快速失败提示，不承担安全职责。
2. **观测效果，不观测过程**：可观测点只在三个交接边界（agent→文件 / 文件→看板 / 看板→人）；"是否读了 SKILL.md"放弃观测，效果可检（输出不含契约结构=整体打回）。
3. **只为故障定位服务**：每层产物带 run manifest（producer/模型/时长/输入指纹/ticket_id/校验结果），故障二分定位：校验挂→产物层；校验过内容错→语义层（locator/golden）；都对看板不对→投影层（watcher 重建）。

### 7.3 Harness"强大"五标志（=验收标准）

产出可机检 / 引用可回溯 / 变更可回归（golden）/ 失败可降级 / 教训可回流。

## 8. 生命周期状态机与门禁

### 8.1 十态状态机

```
S0 线索 → S1 预审 → S2 决策 → S3 解构 → S4 编制 → S5 审查 → S6 封标 → S7 开标 → S8 结果 → S9 归档
```

（合同/交付/回款段二期从 S9 延伸，迁移 kanban 经营闭环。）

### 8.2 门禁矩阵（内嵌于 set-stage）

| 迁移 | 前置门禁 |
|---|---|
| S2→S3 | 阶段 0 产物含 lessons_applied（引用有效教训 ID） |
| S3→S4 | hits 关键词对账 100% PASS |
| S4→S5 | 完整性核验 PASS + 规格单评分点全覆盖 + 评分点-素材匹配率达标 |
| S5→S6 | auditor 阻断级=0 + locator 命中率≥95% + 人工放行签核（L3） |
| S8→S9 | apply_archive 幂等应用 + lessons 采纳确认 |

### 8.3 时间线与跨标一致性

timeline.json 驱动倒计时（答疑截止/保证金/封标/开标），提醒走脚本不走 LLM；`rules/consistency.py` 每日 08:30 跑：人员跨标冲突、证照有效期覆盖投标期、多标资源挤占 → alerts.json → 今日必办。

## 9. 数据流编舞

**判别三问**：确定性数据→脚本；需语义判断→ZCode；周期高频→必须 cron 脚本。

| 数据 | 生产者 | 触发 | 落点 | 看板感知 |
|---|---|---|---|---|
| 标讯抓取 | lead_capture.sh | cron 10:00/16:00 | leads.jsonl | watcher 5s |
| 标讯打分 | bid-scout | cron 跟后/手动 | 线索暂存 | validate 过后转入 |
| stage 推进 | set-stage.sh | 看板命令/CLI | bids.jsonl | 命令即时 |
| 阶段产物 | 主 Agent+skill | 事件 | bids/\<id\>/data/ | watcher（只认 status=final） |
| 章节草稿 | bid-writer | 主 Agent 派发 | bids/\<id\>/draft/ | watcher（进度计数） |
| 审计/复核 | auditor+locator | 阶段门 | audit/ verify/ | watcher（缺陷面板） |
| 预警 | consistency.py | cron 08:30 | alerts.json | watcher |
| digest | digest_stats.py（LLM 可选） | cron 09:00 | digests/ | 直接读 |
| 归档回流 | archivist→apply_archive | 开标后手动 | kb/ + lessons | watcher |

**三条接口铁律**：①ZCode→看板只走文件且只认完稿标记；②看板→ZCode 不直接指挥（一期靠工单+人）；③单一写者（bids.jsonl 只有 set-stage 写；暂存只有 scout 写；看板 SQLite 是可重建投影）。

一天节奏：08:30 预警 → 09:00 digest → 10:00 抓取 → 10:05 scout 打分 → 白天工单开会话跑阶段 → 17:00 封标签核。周期性的醒着（脚本），事件性的聪明（ZCode），人在审批位。

## 10. 强制机制：谁是强制者

**AI 生产"资格的 content"，脚本认证"放行的资格"**。强制实体 = `rules/` 确定性门禁脚本，**物理内嵌在 set-stage**（状态唯一写入口）——无论从看板按钮/命令行/ZCode 会话触发，同一校验必然执行。三处挂载：set-stage 内部（定义级强制）、看板命令（调同一脚本）、pre-commit（产物入 Git 前）。看板只是按门铃的 UI，权限不比命令行大。

| 环节 | 语义生产者 | 确定性强制者 |
|---|---|---|
| kb 回流 | archivist 提案 | set-stage：S8→S9 校验提案存在+已验证+lessons 采纳 |
| 开工读记忆 | 主 Agent（协议，软） | S2→S3 校验 lessons_applied 字段 |
| 素材引用 | 主 Agent 写规格单 | S4→S5 校验评分点-素材匹配率 |
| 资质匹配 | —（纯机检） | precheck_auto.py |
| 产物入 Git | — | pre-commit 同套 gate |

## 11. 提示词工单（Prompt Ticket）

```
看板「生成工单」→ 按任务类型选模板 → 从活数据填变量（bid_id/stage/缺陷数/路径/队列项）
  → ①复制框（给人）②queue/<ticket_id>.json（存档）
人复制 → 在 bid-master 目录开 ZCode 粘贴 → 会话启动 → 产物 run manifest 记 ticket_id
  → watcher 对账 → 看板消单（生成→已执行→已消单）
```

- **ticket_id 闭环**：复制动作本身不可追踪，但工单与产物经 ticket_id 重新对上——可回答"哪个工单产出哪些文件、耗时多少"
- **三条纪律**：工单给路径和目标不内嵌大段内容；完成条件=门禁清单原文（会话第一秒知道验收标准）；模板库按任务类型固化并进 Git（改模板=改生产指令，走提案流）
- **传输层可替换**：一期人肉复制，二期 CronCreate 定时消费 queue/，工单格式不变。**W1 实测注记**：调度准时但交付时延分钟级以上（实测 ~17min，且首次触发存在零产物窗口）→ 自动消费仅适合**隔夜批处理类**工单；当日必办类维持人工复制（人=审批位）。

## 12. 外部工具收割与冲突规则

### 12.1 收割模式（harvest，零侵入）

```
lingxi-claw / WorkBuddy / Trae 照旧写各自目录（BAW 只读不写）
  → cron ingest.py 扫最新增量（识别：招标txt→source / audit.json→二手源 / xlsx→线索）
  → ~/.bidmaster/inbox/<来源>/<批次>/（追加式，批次隔离，永不覆盖）
  → 幂等（内容指纹判重）+ 脱敏过滤 → validate → 转正（data/ 或 leads）或 rejects/（带原因）
  → 溯源标记 producer=zcode-main / bid-writer / lingxi-claw / trae / human
```

接入分级：L0 手动丢 inbox（当天可用）→ **L1 cron 收割（推荐）** → L2 对方主动投递（可选）。

### 12.2 冲突避免五规则

1. 目录所有权：单一写者扩展——ZCode 写 bids/\<id\>/，外部写各自目录，inbox 唯一共享区且追加式
2. 单实例摄取：ingest.py 加 flock
3. 数据权威线：同标多源不合并，bid_id 目录为主场，外部结论作二手源挂靠（source=secondary，东莞银行标先例），字段级冲突人裁决+记 lessons；producer 标记让看板显示"这条结论谁产的"
4. 会话并发：同一 bid 同时只开一个 ZCode 会话（运行协议）；违反时 git diff 兜底
5. 数据面/代码面分离：~/.bidmaster 只允许 BAW 体系写；代码仓库多工具并用靠 git 分支约定

## 13. ZCode 能力边界实测结论（2026-09-10）

| 事项 | 结论 |
|---|---|
| 项目级 agent | ✅ `.zcode/agents/` 支持（bid-scout 实证） |
| agent pin 模型 | ✅ frontmatter model 字段（bid-scout pin GLM-5.3-Flash） |
| 后台并行 | ✅ Agent run_in_background |
| 子智能体自动编排/互通信 | ❌ 真边界——循环打回由主 Agent 多轮驱动 |
| Hooks | 存在（mimosa 实例），门禁用 pre-commit+set-stage 更稳 |
| 闲时任务 | 不可验证，用 CronCreate 替代（已验证存在） |
| 看板拉起 ZCode | ❌ 无对外 API；用工单衔接 |
| Memory | ✅ 项目级持久记忆生效 |
| W1 待实测 6 项 → **已测毕（2026-09-10，`log/w1-verify.md`）** | ✅ 后台并行汇合、子智能体 Read SKILL.md 契约；⚠️ tools 只读强制（需重启复测，已按三层防御设计）、CronCreate 消费（调度准时但交付延迟 ~17min，一期人工复制）；❌ 异档去相关（同家族双盲检出差异=0→auditor 改主档单模型+人工抽检加密）、CLI 带 prompt 启动（桌面版无 CLI 入口→纯复制粘贴，机制不受损） |

## 14. 合规红线

- 材料三级：L1 公开（体验期只用此级）/ L2 内部一般（脱敏后用）/ L3 敏感（成本价/折扣/客户名单/人员证件号——**不进外部模型 prompt**，index 只存元数据不存敏感编号）
- 脱敏机检：desensitize.py 正则库挂 inbox→转正路径，拦截率要求 100%（模式库覆盖身份证/手机/证书编号）
- Memory 残留：涉密项目关闭 ZCode Memory；任务结束清理工作区中间产物

## 15. 风险与降级矩阵

| 风险 | 等级 | 降级路径 |
|---|---|---|
| ZCode/Bigmodel 不可用（开标前夜） | P0 | 全部关键路径有无 LLM 降级：scout→lead_capture 裸抓+人工筛；auditor→BD-0025 机检+人工清单；writer→人工按规格单写；digest→stats 纯数据 |
| 子智能体产出不可信 | P0 | 信任零假设：主 Agent 重跑校验 + gate 双保险 |
| 改名迁移路径断裂 | P1 | W1 迁移清单逐项核对（.zcode 随迁/start.sh 相对路径/README 旧路径/memory 更新） |
| PDF 表格丢失（阳光平台 txt 先例） | P1 | 单章验证解析质量；评分附表 OCR 后入区；二手源标记 source=secondary |
| set-stage 门禁串行超 2s | P2 | 校验结果缓存进 bids.jsonl stage 元数据 |
| token 超预算 | P2 | Flash 承担高频；writer 分章并行控制批量；记录每标实际消耗 |
| 时间不足 | P2 | 优先级 M1>M2>M3>M4；M1+M2 达成即具备最低提交条件 |
| CronCreate 交付时延分钟级 | P2 | 当日时效任务走人工复制工单；自动消费仅限隔夜批处理类（W1 实测 5） |
