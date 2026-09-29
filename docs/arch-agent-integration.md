# AI Agent 嵌入层融合方案（arch-review v0.6 增补件 · §5.7 扩展）

> 日期：2026-09-11 · 状态：**方案待 owner 评审**（与 arch-review-v0.6 同批）
> 定位：补齐 arch-review 未覆盖的深度融合——**ZCode（含 skill）、其他 AI agent（含 skill）、bid-master 看板、llm-wiki、truth.db 五者的接触面契约化**。
> 关系：本文扩展 arch-review §5.7（AI 层）并修订 §5.2（kb_assets 由"可选二期"升为一期必做）；不推翻其 P0–P3 主线，只向各期**增补任务**。
> 第一性判据：**AI 运行时是系统的唯一生产者，但它不是系统的一部分**——ZCode 会话随时消失（P0 风险：ZCode 不可用）。因此融合的正确形态不是"把 agent 编排进系统"，而是**把 agent 与系统的每个接触面都变成契约+登记**：agent 来了按契约干活，走了系统照转。

---

## 1. 第一性推导：Agent 与系统只有五个接触面

去掉所有实现细节，任何 AI agent（ZCode 子智能体、主 Agent 会话、外部 lingxi-claw/Trae/WorkBuddy、未来接入的任何运行时）与系统只可能有这五个接触面：

| 接触面 | 问题 | 契约化载体 | 现状 |
|---|---|---|---|
| **① 触发面** | 谁在何时启动它、带着什么任务 | `tickets` 表状态机 + 工单模板 | ⚠️ queue/ 文件未入库（tickets=0 行），回执缺失 |
| **② 输入面** | 它读什么才算"按规矩干活" | SKILL.md（工艺）→ `contracts/`（合格判据）→ kb 指针（素材）→ lessons（教训） | ⛔ SKILL.md 与 contracts 无同步机制；契约三处漂移正在发生 |
| **③ 产出面** | 它写什么、经哪里、算不算数 | `store.register_artifact()`（schema 校验+指纹复算）+ `store.register_run()`（manifest 入库） | ⛔ register_artifact 全仓 0 调用（arch-review A2） |
| **④ 知识面** | 它的经历如何变成下一标的能力 | llm-wiki 生命周期：产物→切片→教训→supersession→衰减 | ⚠️ lessons/kb 与 truth.db 脱节（lessons 表 0 行） |
| **⑤ 观测面** | 人如何看到它干了什么、花了多少、卡在哪 | 看板 System 层（runs/gate_attempts/tickets 聚合）+ Now 层（agent 卡点入必办） | ⛔ "AI 看板"的 AI 在看板上不可见（arch-review §3.3） |

**融合 = 五面全部契约化 + 入库**。缺任何一面，agent 就是系统里的黑盒或野马：
- 缺①：任务无回执，"哪个工单产出哪些文件"不可答（B3）；
- 缺②：契约改了 skill 不改 = 下一轮漂移（S3→S4 病根的复刻）；
- 缺③：文件"看起来在"就算数，幻觉流入（I2 违反）；
- 缺④：飞轮断——教训只在 md 文本里，门禁校验读不到权威层；
- 缺⑤：单人的注意力瓶颈得不到 AI 侧的供给。

---

## 2. 融合总图

```
┌─ AI Agent 运行时层（生产者，可插拔）────────────────────────────────────┐
│                                                                        │
│  ZCode 会话（一等生产者）                                               │
│   ├─ 主 Agent（语义主链路：解构/规格单/关键件/价格）skills/bid-master/   │
│   └─ 子智能体×5（scout/writer/locator/auditor/archivist）+ SKILL.md×5    │
│                                                                        │
│  外部 agent（二手源生产者）          未来 agent（同契约接入）             │
│   lingxi-claw / WorkBuddy / Trae      任意 CLI/IDE 运行时               │
└────┬─────────────┬──────────────┬──────────────┬────────────────────────┘
  ①触发          ②输入          ③产出          ④知识
   │              │              │              │
   ▼              ▼              ▼              ▼
 tickets 表    contracts/      store.register   llm-wiki 生命周期
 generated →   artifact/*.json  _artifact()      （crystallization/
 dispatched →  gates/*.json    （schema 校验      supersession/衰减）
 executed →    commands/*      +指纹复算，             │
 consumed      SKILL.md 渲染    生产者不得自报          ▼
 （回执=        门禁清单）      final）          lessons 表（权威）
 runs.ticket_id                     │          kb_assets 表
   │              │              ▼               │ md 渲染（可读层）
   │              │        artifacts 表           │
   │              │        runs 表                │
   │              │        citations 表 ──────────┤
   ▼              ▼              ▼                ▼
 ┌──────────────── truth.db（单一权威 I1）──────────────────┐
 │ bids/stage_history/gate_attempts/artifacts/runs/        │
 │ citations/tickets/lessons/kb_assets/alerts/config       │
 └───────────────────────┬─────────────────────────────────┘
                         ▼ ⑤观测（只读连接，零镜像）
 ┌─ bid-master 看板（三层注意力）───────────────────────────┐
 │ Now：今日必办（含 agent 卡点）  Bid：深潜（证据反查带    │
 │ producer/run）  System：Agent 运行时面板（名册/成本/    │
 │ 通过率/工单三态/门禁通过率）                              │
 └─────────────────────────────────────────────────────────┘
```

**图上每条边都是一条契约，每条契约都可机检（进 make gate）**——这是与"缝合式桥接"（v0.4 的 server.py BAW 段）的本质区别。

---

## 3. A · ZCode 嵌入细则（一等生产者）

### 3.1 Agent 接入契约（每个 agent 一行，进 `contracts/agents/*.json`，make gate 校验与 .zcode/agents/*.md frontmatter 一致）

| Agent | ①触发 | ②输入 | ③产出契约（kind） | ③登记命令 | 只读边界 |
|---|---|---|---|---|---|
| 主 Agent | 工单 new-bid-analysis（人工复制启动） | 五阶段工艺书 + contracts + lessons + kb 指针 | stage0/hits_recon/response_matrix/spec/price/关键件 | 每产物 register_artifact + register_run | 写仅限本标工作区 |
| bid-scout | 工单/手动（cron 二期） | 打分契约 + 画像 config | lead | register_artifact(producer=bid-scout) | 只写线索暂存 |
| bid-writer | 主 Agent 派发（分章并行） | spec.schema + 素材指针 + 白名单 | draft 章 + manifest | register_artifact(kind=draft) + register_run | 无联网/无 Bash |
| bid-locator | 主 Agent（阶段产物落盘后） | 定位工艺 + samples schema v2 | locator-report | register_artifact + register_run | **只读三件套** |
| bid-auditor | 阶段门/工单 audit-round | audit 规则库 + 被审产物 | audit-rN | 主 Agent 落盘后登记 + register_run | **只读三件套** |
| bid-archivist | 开标后手动/工单 | 全工作区 + lessons 表 | proposal/lessons 草案 | register_artifact + register_run | 只写 archive/ |

**落地形态**：agent .md 的 frontmatter 不变（ZCode 消费），`contracts/agents/*.json` 是系统侧的登记副本——**reconcile 扩展一项**：`.zcode/agents/` ↔ contracts/agents/ 双向对账（改名/换模型当天可见）。

### 3.2 SKILL.md ↔ contracts 同步机制（消灭"契约改了 skill 不改"）

- SKILL.md 中"完成条件=门禁清单原文"**不再手写**，改为引用一行：`完成条件：见 contracts/gates/s3-s4.json 的渲染（make gate-cards --gate s3-s4 输出）`；
- `make gate` 新增 `gate-skills` 目标：抽取每个 SKILL.md 中出现的产物文件名/schema 字段，与 `contracts/artifact/` 比对——**漂移即红**；
- 工单模板 `rules/tickets/*.json` 的 done_when 同源渲染（工单/门禁/skill 三处一个源头，I3 彻底落地）。

### 3.3 主链路工艺手册（P0-5 扩充）

`skills/bid-master/SKILL.md` 除五阶段流程外，必须写死三条融合纪律：
1. 每个阶段产物落盘后**立即** `store.register_artifact()`（不给"稍后统一登记"留口子）；
2. 每次会话结束 `store.register_run()`（含 ticket_id）——这是工单回执的唯一来源；
3. 关键件（投标函/偏离表/价格）**禁止派发子智能体**（D7 单上下文铁律的工艺化表述）。

---

## 4. B · 其他 AI agent 嵌入（二手源生产者）

- **收割即登记**：`ingest.py` 每收一个文件，除落 inbox 外**同步 register_artifact(producer=lingxi-claw|workbuddy|trae)**——二手源与一手源进同一张 artifacts 表，`producer` 字段区分权威级（一手=ZCode 会话，二手=外部收割）；
- **二手源引用规则**进 contracts：citations.target 加 `source` 枚举（primary/secondary）——东莞银行标先例的契约化；auditor/writer 引用二手源产物必须带 secondary 标，看板深潜页证据反查时**显式区分显示**"此断言依据来自外部工具产出"；
- **不升级为信任**：二手源产物永远 `status=registered`，不得被门禁提升为 final（二手源只作佐证，不作门禁凭据）——这是"只读收割"在登记制下的语义升级。

---

## 5. C · 看板融合（⑤观测面）

### 5.1 System 层新增「Agent 运行时」面板（F6 扩展为 F6a/F6b）

| 面板 | 数据源 | 5 秒回答 |
|---|---|---|
| **F6a Agent 名册** | contracts/agents/*.json ↔ .zcode/agents/（reconcile 对账） | 有哪些 agent、各 pin 什么模型、定义是否漂移 |
| **F6b 运行台账** | `runs` 表聚合（按 agent/标/月：次数/token/时长/self_check 通过率） | AI 干了什么、花了多少、质量趋势 |
| F5 工单三态流 | `tickets` 表 | 任务在谁手里、卡在哪 |
| 门禁通过率 | `gate_attempts` 聚合 | 哪道门常拦、拦截原因 TopN |

### 5.2 Now / Bid 层的 agent 痕迹

- **Now**：gate_attempts 失败项 + tickets 超时未消单项 → 今日必办（"auditor round-2 已生成 4 小时未执行"这类条目）；
- **Bid 深潜**：证据反查每条 citation 显示 `producer + run_id`——"这个断言是 writer 在哪次运行里产的、被 auditor 引用过几次"一键可见；缺陷面板关联 runs（哪轮审计、什么模型）。

### 5.3 前后端一致性协议（四层，2026-09-11 owner 追问补齐）

一致性不靠"同步机制做得强"，靠**删掉不一致的可能性**：

| 层 | 机制 | 可机检判据 |
|---|---|---|
| **L1 数据：单一读源 + 傻前端** | 前端只经 read_models API（`GET /api/views/<name>`）取数——不直连 DB/文件/jsonl；读模型=纯 SQL 视图函数（参数绑定）；前端零计算纯渲染（漏斗计数/通过率/token 合计全部服务端算好，本地不派生任何状态）。**一致性级别显式声明：读己之写 + 秒级最终一致**（命令响应为同步强一致），不引入 WebSocket/状态机库 | 前端源码扫描无直连数据源（gate-hygiene 扩展）；read_models 无业务推导（单测断言纯 SQL） |
| **L2 变更传播：epoch 戳 + SSE + 兜底** | truth.db `meta` 表存 `epoch`（整数），store 每次写事务提交 `epoch+1`（参数绑定）——变更感知从 5s 全量重扫降为**查一个整数**；server 进程内写（命令）提交后直接广播，进程外写（CLI/其他会话）轻询 epoch（1s 或 PRAGMA data_version）检测后重算读模型再广播；SSE 事件带 epoch，前端比对本地 epoch 不同才重拉对应视图；SSE 断线 30s 兜底全量拉（沿用现有）自愈 | 任何写入 ≤1s（进程内）/≤2s（进程外）看板可见（联调测试进 quality-test） |
| **L3 接口契约：read model 也进 contracts** | 每个 read model 一份 `contracts/readmodels/<name>.schema.json`（响应结构+字段+`x-ui` 渲染提示）——补上 contracts 面的最后空白（原只覆盖产物与门禁）；`make gate` 增 `gate-readmodels`（种子库实例化响应做结构断言）；前端对 schema 外字段**显式失败**（渲染"字段缺失"标记，fail-visible 不静默吞） | 后端改字段 → gate 红 + 前端显式缺位（而非静默空白） |
| **L4 操作回执：命令响应即真相，禁乐观更新** | 所有写走 commands，事务提交后结果同步返回（含门禁拒绝的 blockers 结构化清单）；前端不做乐观 UI（按钮→等响应→成功刷新/被拦渲染卡点）——单用户无延迟焦虑，乐观更新省毫秒、引入一整类不一致 bug，不做；**门禁失败尝试也落 gate_attempts**，拒绝瞬间卡点面板即可见（失败与成功同一套传播） | advance_stage 被拦时前端卡点面板出现该条 gate_attempt（联调断言） |

epoch 机制同时兑现 arch-review A4 技术债："watcher 每 5s 全量重扫 bids/*" 在读模型化后自然消亡（不再扫目录，只查 epoch）。

---

## 6. D · llm-wiki 融合（④知识面，修订 arch-review §5.2）

**原则：DB 是权威，md 是渲染**（与 bids.jsonl 同构的可读层，llm-wiki 的"可读性"价值不丢）：

| 知识域 | 权威层 | 渲染层（llm-wiki 可读） | 生命周期机制 |
|---|---|---|---|
| 教训 lessons | `lessons` 表（L-* ID 唯一、supersession、status） | `memory/lessons.md`（store 写表后自动导出） | supersession 写入时旧条目自动置"沉淀"；cron 每日扫描"超 1 年未引用且被取代"置"归档" |
| 案例/方案/证照/人员 kb | `kb_assets` 表（**一期必做**，arch-review 的"可选二期"升格） | `kb/index/*.json`（导出） | `expires_at` 衰减：consistency.py 读表出告警（不再读 JSON） |
| 切片 slices | 生产层文件（L2/L3 不入库） | — | 指针经 citations 引用，指纹登记防漂移 |

**飞轮闭环入库**：archivist 提案 confirmed → `apply_archive` 改写 `lessons`/`kb_assets` 表（SQL 参数绑定，走 store 唯一写口）→ 自动导出 md/index 渲染 → 下一标 S2→S3 门禁读表校验 lessons_applied——**"教训可回流"从 md 文本约定变成 DB 事实**（acceptance §3.6 飞轮闭环的可机检形态）。

---

## 7. E · 数据库融合（新增/修订表与守护）

| 表 | 来源 | 增补字段（相对 arch-review §5.2） |
|---|---|---|
| `runs` | arch-review 已列 | + `agent`（名册 ID，外联 contracts/agents）、`tokens_in/out` |
| `citations` | arch-review 已列 | + `producer`、`source`（primary/secondary）、`run_id` |
| `tickets` | 已有 | + `dispatched_at`（四态机见 §8） |
| `kb_assets` | **升格一期必做** | domain/id/file/fingerprint/expires_at/sensitive/last_referenced_at |
| `agent_registry` | 本文新增（可选） | 名册快照表；若不建则 System 面板直读 contracts/agents（二选一，P2 定） |

**reconcile 扩展三项**（arch-review §5.2 守护的增补）：
1. truth.db.artifacts ↔ 生产层文件指纹（已有）；
2. `.zcode/agents/*.md` frontmatter ↔ `contracts/agents/*.json`（名册漂移）；
3. `kb_assets` ↔ `kb/index/*.json` 导出（渲染漂移）。

全部 SQL 参数绑定（store 唯一写口，安全约束不变）。

---

## 8. 工单状态机完整定义（①触发面闭环，补 arch-review B3）

```
generated ──人复制工单──▶ dispatched ──会话执行+register_run(ticket_id)──▶ executed ──reconcile 按 runs.ticket_id 对账──▶ consumed
    │                        │                                                    │
    └── 超时未 dispatch（cron 每日检查）→ alerts                                └── 消单时回写 consumed_artifacts
```

- **回执的权威来源 = runs.ticket_id**（不再"扫文件目录猜"）：reconcile 只查 `runs` 表，工单与产物的对应关系由 agent 侧登记时的 manifest 保证（I2 的自然延伸）；
- 看板命令注册：`ticket.generate/list/reconcile`（PRD §4 补齐），生成即写 tickets 表；
- CronCreate 隔夜批只允许处理 `generated→dispatched`（批派发），不越权到 executed（执行仍需人启动的会话——人在环不变）。

---

## 9. 落地排期（向 arch-review P0–P3 增补，不新开期）

| 期 | 增补任务 | 验收 |
|---|---|---|
| **P0**（+0.5 天） | ③产出面止血：register_artifact/register_run 接进 ingest（收割即登记）与 ticket.reconcile（回执改查 runs 表） | 外部收割文件在 artifacts 表可见（producer=lingxi-claw）；reconcile 不再扫目录 |
| **P1**（+1 天） | ②输入面契约化：contracts/agents/*.json 六份 + make gate 增 gate-skills 同步检查 + SKILL.md 完成条件改渲染引用 | 契约/门禁/skill 三处任一改动，其余两处在 gate 报红 |
| **P2**（+1 天） | ⑤观测面：System 层 Agent 运行时面板（F6a/F6b）+ Now 层 agent 卡点 + 深潜证据带 producer/run_id + **前后端一致性协议四层（§5.3：epoch/SSE/readmodel 契约/禁乐观更新）** | 首页 5 秒回答第四问："AI 干了什么、花了多少？"；写入 ≤2s 可见；后端改字段 gate 红 |
| **P3**（+1 天） | ④知识面：kb_assets 一期 + lessons 表权威化（apply_archive 改写表）+ 衰减 cron | 飞轮闭环全入库：归档→表→渲染→门禁读表，全程可机检 |

**总增量 ≈ 3.5 天**，与 arch-review 的 P0(1)+P1(2-3)+P2(3-4)+P3(2) 合并后仍在单人两周量级内。

---

## 10. 验收判据（每面一条，全部可机检）

| 面 | 判据 | 检查方式 |
|---|---|---|
| ①触发 | 任意 consumed 工单可反查其全部产物与 run | `SELECT * FROM runs WHERE ticket_id=?`（参数绑定） |
| ②输入 | 任一 SKILL.md 的产物清单与 contracts 一致 | `make gate`（gate-skills） |
| ③产出 | 真实标工作区无"未登记产物"（生产层文件 ⊆ artifacts 表） | `rules/reconcile.py --check` |
| ④知识 | lessons_applied 引用的每个 L-* 存在于 lessons 表且 status=active | S2→S3 门禁（读表） |
| ⑤观测 | 看板 System 页能看到每个 agent 最近 7 天运行次数/ token/通过率 | 人工验收 + read_models 单测 |

---

## 11. 决策结果（2026-09-11 owner 拍板，并入 arch-review §11 决策记录）

| # | 决策 | 结论 | 备注 |
|---|---|---|---|
| Q4 | agent_registry 表建不建 | **B 不建** | System 面板直读 contracts/agents 文件；reconcile 保证 ↔ .zcode/agents 一致 |
| Q5 | 收割即登记的粒度 | **B 只登记投标相关件 + 预留按需扩展** | 登记类型清单**配置驱动**（config `ingest_register_types`，初值 tender/audit-data/checklist），不硬编码——后续按需增类只改配置+自测，不动 ingest 逻辑；未登记件留 inbox（registry.json 全量指纹可查） |
| Q6 | 融合增补并入范围 | **随 Q3=C 全部并入** | 本轮 = 主件 P0+P1+P2 + 增补件 P0/P1/P2/P3 全部段；主件 P3（citations 采集/第 2 基线/一天演练）顺延下轮 |

执行序列（落地排期 §9 与 Q2=C 产物重做路径合并）：
**P0**（契约 schema 前置 + 止血 + 增补产出面）→ **P1**（契约收敛 + agent 契约/gate-skills）→ **P2**（看板重构 + Agent 面板 + 一致性协议四层）→ **增补 P3 段**（kb_assets + lessons 表权威化 + 衰减 cron）。
