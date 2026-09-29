# bid-master 第一性原理深度分析 & v1.0 重构方案

> 分析日期：2026-09-11 · 对象：`~/Documents/bid-master`（HEAD `ff18bec` / v0.5.0）+ `~/.bidmaster`（数据面）+ `~/.bidboard`（遗留面）
> 方法：第一性原理（拆到不可再分的目标与约束，再与现状逐条对账）+ 全量实证复核（**每条结论附可复现命令**）
> 状态：**已定稿（Q1–Q6 全部拍板，2026-09-11）· 进入执行**——落地开发计划见 §8（含融合增补 `docs/arch-agent-integration.md` 全部任务）；决策记录见文首与 §11

### 决策记录（滚动）

| 日期 | 决策 | 选项 | 影响 |
|---|---|---|---|
| 2026-09-11 | **Q1 legacy 看板处置 = 合并进 truth.db 后删除 legacy 模型** | B | `~/.bidboard` 的 7 旧标 / 55 线索 / 13 步流程视图 / 管理视图需写迁移与字段映射（`code`↔`bid_id`、`lifecycle`↔`stage`、`priority/tier` 等），完成后 legacy 表与视图下线；此项并入 P0/P1，作为"单一权威"的硬验收 |
| 2026-09-11 | **增补件《AI Agent 嵌入层融合方案》成立**（`docs/arch-agent-integration.md`）：扩展本方案 §5.7，修订 §5.2（kb_assets 由可选二期升一期必做）；新增决策 Q4/Q5/Q6 见增补件 §11 | — | 本方案 AI 层四个缺口（agent 接入契约缺失 / llm-wiki 在目标架构中消失 / 工单回执机制缺失 / SKILL↔契约无同步）由增补件承接；落地增量 ≈3.5 天并入 P0–P3 各期 |
| — | **Q2 门禁收紧 vs 真实标 = C 真实标产物重做**（owner 定 2026-09-11）：用主 Agent 按 P1 新契约重新生成 GOLD 阶段产物（hits_recon/response_matrix 等）。影响：契约 schema 设计前置到 P0（先定契约再重做产物，避免二次返工）；解构语义不重跑，仅产物**格式重铸**+登记 | C | P0-1 改为产物重做路径；token 成本增量预估 <50 万 |
| — | **Q3 本轮范围 = C 一路到 P2 含融合增补全部**（owner 定 2026-09-11）：主件 P0+P1+P2 + 增补件全部段（含 Agent 面板/一致性协议/kb_assets 与 lessons 权威化）。**主件 P3（citations 采集/第 2 基线/一天演练）顺延下轮** | C | 执行序列见增补件 §9 与 DEV-0021；单人 ≈8–10 天，风险窗口拉长已接受 |

---

## 0. 摘要（结论先行）

系统不缺功能，缺**收敛**。三句话概括：

1. **可信性缺口**：真相源名义上已收敛到 `truth.db`，实际权威仍在文件系统与遗留库。`truth.db` 的 `artifacts / lessons / tickets` 三张表全为 **0 行**，`store.register_artifact()` **全仓无调用方** → AGENTS.md 第 1 条的"登记制"是声明，不是事实。
2. **闭环缺口**：真实标 `2026-GOLD-jishu` 停在 S3，而 S3→S4 门禁要求的 `data/hits_recon.json`、`data/completeness.json`、`verify/locator-report.json` 在其工作区**根本不存在**（实际产物是 `hits.json`、`完整性核验.md`）→ 门禁契约与生产者契约漂移，**真实标按现有链路推不动**。
3. **看板缺口**：目标是"解决方案专家的日常工作看板"，实际首页展示的是**遗留的 7 条旧标**（`code/lifecycle` 模型），新 BAW 的 3 个标只以一个 4 列表格 + alerts 挂在页尾；PRD v6 §3 的 7 视图只落地约 2.5 个。

**根治方向一句话**：
> **一个真相源**（truth.db 单一权威）＋ **一份契约**（schema 驱动"写口 / 门禁 / 看板"三处复用）＋ **一个门禁内核**（声明式规则 + 结构化结果）＋ **一条证据链**（citations 入库，断言可反查）＋ **一块注意力面板**（Now / Bid / System 三层）。

**成本量级（定稿版，含融合增补）**：P0 契约前置+止血+产出面 ≈1.5 天；P1 契约收敛+agent 接入契约 ≈3 天；P2 看板重构+Agent 面板+一致性协议 ≈4 天；P3' 知识面入库 ≈1 天。**合计 ≈9–10 天，按期分四段提交（每段可独立回退）**。主件 P3（citations 采集/第 2 基线/一天演练）顺延下轮。**P0 不做则 P1 之后全部是沙上建塔**。

---

## 1. 分析口径

### 1.1 第一性四问（对每个模块都问一遍）

| 问 | 判据 |
|---|---|
| Q1 它的**不可再分的目标**是什么？ | 去掉所有实现细节后，它必须保证的一件事 |
| Q2 它的**权威副本在哪**？ | 出冲突时以谁为准，谁有写权 |
| Q3 它的**契约**（输入/输出/合格判据）在哪一处定义？ | 是否单点，是否可机检 |
| Q4 它**失效**时的可观测性与降级路径？ | 出问题时人多久能看到、能不能顶上 |

### 1.2 复核命令（本文所有数字均可复现）

```bash
# 真实层 vs 各副本
sqlite3 ~/.bidmaster/truth.db "select 'bids',count(*) from bids union all select 'artifacts',count(*) from artifacts union all select 'lessons',count(*) from lessons union all select 'tickets',count(*) from tickets union all select 'stage_history',count(*) from stage_history"
sqlite3 ~/.bidmaster/out/projection.db "select * from projection_bids"
sqlite3 ~/.bidboard/bidboard.db "select count(*) from bids; select * from baw_mirror_bids"
wc -l ~/.bidmaster/memory/bids.jsonl
# 契约漂移
cd ~/.bidmaster/bids/2026-GOLD-jishu && for f in data/hits_recon.json data/completeness.json verify/locator-report.json data/stage0.json; do [ -e "$f" ] && echo "OK $f" || echo "MISS $f"; done
grep -rn '"status"' --include=*.json ~/.bidmaster/bids | grep -c final
# 门禁与工程
make gate && make regress ; crontab -l
grep -rn "register_artifact" --include=*.py ~/Documents/bid-master | grep -v 'rules/store.py'
```

---

## 2. 第一性重述：这个系统到底是什么

### 2.1 从业务本质推导

解决方案专家做投标，去掉行业术语后只有三个动作：

1. **判断**：这个机会要不要投（资质/内定信号/资源/时间）。
2. **证明**：用**可追溯的证据**证明"我们满足要求"——招标原文 → 响应条目 → 素材/方案 → 最终文件。
3. **交付**：在截止时间前把材料闭环提交，且**零废标**。

由此得到系统的第一性对象，**不是"任务卡"，而是"证据 + 门禁 + 决策位"**：

| 第一性对象 | 定义 | 为什么不可省 |
|---|---|---|
| **证据（Evidence）** | 一条断言 + 其原文锚点（页·章节·逐字）+ 承载产物 | 投标的失败几乎都源于"说了但没有依据" |
| **门禁（Gate）** | 确定性校验，决定"状态能否前进/能否提交" | 没有它，状态就只是自我报告 |
| **决策位（Decision）** | 必须由人做的判断（投不投、放不放行、归不归档） | AI 不能承担废标责任 |
| **注意力（Attention）** | "此刻只有 N 件事需要我" | 单人作战，注意力是唯一瓶颈资源 |

### 2.2 五条不变式（Invariants，重构的验收尺子）

| # | 不变式 | 违反的后果 |
|---|---|---|
| **I1** | **单一权威**：每个事实只有一个写者、一份权威副本；其余皆为可弃投影 | 冲突时无人知道以谁为准 → 状态不可信 |
| **I2** | **登记制**：产物必须被权威层登记（指纹复算）才算数，生产者不得自证合格 | 文件"看起来在"就算数 → 幻觉/半成品流入 |
| **I3** | **契约单点**：同类产物的"合格"定义只存在一处，写口/门禁/看板共用同一 schema | 门禁与生产者漂移 → 真实标推不动（当前正在发生） |
| **I4** | **证据闭合**：每个对外断言可回溯到原文锚点，反查路径不依赖记忆 | 评标翻车无法定位，复盘无法沉淀 |
| **I5** | **人类在审批位**：所有不可逆动作（放行/归档/升级）留人名与时间戳 | 责任链断裂 |

### 2.3 "解决方案专家的 AI 看板"的正确定义

不是"把状态画成卡片"，而是**三层注意力模型**：

```
① Now（今日，进来看 5 分钟）   只有"需要我决策/有截止压力/有阻断风险"的条目
② Bid（单标，盘中深潜）        一条纵向链路：阶段 → 门禁卡点 → 产物 → 证据 → 缺陷 → 成本
③ System（系统，周度体检）     agent 名册与运行记录 / 门禁通过率 / token 成本 / kb 体检 / 工单队列
```

判据（可验收）：**打开首页 5 秒内能回答三个问题**——"今天我必须做什么？""哪个标有废标风险？""AI 干了什么、花了多少、产出去哪了？"
以这把尺子量现状：三个问题**都答不出来**。

---

## 3. 现状诊断（按不变式逐条对账）

### 3.1 架构层

#### A1 ⛔ 同一"标的状态"存在 **5 份副本**，且已实测漂移

| 副本 | 位置 | 实测内容 | 写者 |
|---|---|---|---|
| ① truth.db（声称权威） | `~/.bidmaster/truth.db` | 3 real（S2/S2/S3） | `rules/store.py` |
| ② 兼容导出 | `~/.bidmaster/memory/bids.jsonl` | 3 行 | store 导出 |
| ③ 投影库 | `~/.bidmaster/out/projection.db` | **4 行**，含已清理的 demo `2026-demo-w2b`；real 标 stage 与 ①**不一致** | `rebuild_cache.py`（跑过一次，之后无维护） |
| ④ 看板镜像表 | `~/.bidboard/bidboard.db :: baw_mirror_bids` | 3 行 | server watcher 5s |
| ⑤ 遗留看板模型 | `~/.bidboard/bidboard.db :: bids` | **7 条旧标**（`code/lifecycle/priority` 另一套模型） | server 命令层 |

**根因**：v0.5.0 引入 DB 权威，但"看板不拥有状态"被错误地实现为"看板再存一份镜像"；同时 legacy 模型未退役、投影未纳入守护。
**后果**：任何一次状态对不上账，需要人工判断以谁为准；"删库重建即恢复"未被验证（现在重建正好会暴露 ③ 与 ① 不一致，且 ② 是 ②，不是 ①）。

#### A2 ⛔ 登记制没有写者：`artifacts=0 / lessons=0 / tickets=0`

- `rules/store.py` 有 `register_artifact()`（含指纹复算），**全仓无任何调用方**；只有 `docs/truth-layer-plan.md` 和 `AGENTS.md` 提到它。
- 门禁 `set_stage.py` **直接读文件系统**（`ws/data/xxx.json`），完全不查 `artifacts` 表。
- 看板 watcher 走 `rules/kanban_baw_bridge.py` **扫目录**。

**根因**：v0.5.0 只改造了"状态写口"，没有改造"产物写口"和"读口"。
**后果**：`artifacts.status(registered/final/confirmed)` 的状态机形同虚设；I2 不成立；所谓"生产层写后必须登记"是纪律口号，无强制者。

#### A3 ⛔ 同一份"合格"定义散落三处，且互相矛盾（I3 违反）

| 关注点 | 门禁（set_stage）认为 | 生产者实际产出 | 看板（bridge）认为 |
|---|---|---|---|
| 阶段产物文件名 | `data/hits_recon.json`、`data/completeness.json` | `hits.json`、`完整性核验.md` | 任意 `data/*.json` |
| 产物有效性 | **不看 status**，只看文件在不在 | 多数 `data/*.json` **无 status 字段** | **只认 `status=final`**（故基本看不到） |
| locator 报告 | `verify/locator-report.json`（samples 复算） | **不存在** | — |

**实测**：`2026-GOLD-jishu` 停在 S3，但其工作区**缺 S3→S4 门禁所需的全部文件**；同时它的 `data/stage0.json` **没有 `lessons_applied` 字段**（S2→S3 门禁必拦项），却在 truth.db 里是 `S3` 且 `bootstrapped=0` —— 该阶段值来源不可考。
**后果**：**门禁在真实数据上从未通过**；真实标推不动；"闭环"是纸面的。

#### A4 ⚠️ 服务层是 3058 行单体，且横跨两个数据根

- `server.py` 3058 行 / 151 KB，约 50 个顶层函数；`do_GET` 单函数 280 行 if-elif 链。
- 同时硬编码 `~/.bidboard/bidboard.db`（遗留权威）与 `~/.bidmaster`（新数据面），并跑**两个 watcher 线程**（`~/.bidboard/*.jsonl` 与 `~/.bidmaster`）。
- 遗留表 8 张（`bids/leads/lead/events/archive/command_execution/activity_log/collection_run`）+ BAW 镜像 2 张。
- 已知技术债有记录：watcher 每 5s **全量重扫** `bids/*`；升级 `rules/` 后必须重启 server（进程内 import）；镜像表与 projection.db 双读并存待统一。

**根因**：v0.3.2 的看板与 BAW 是两次独立设计，用"薄桥接"缝合而非同一模型两个视图。
**后果**：每加一条能力要改同一文件的多段；无法单测；理解成本随行数线性上升。

#### A5 ⚠️ 主链路工艺手册真空

- `skills/` 只有 5 个**子智能体**角色包（scout/writer/locator/auditor/archivist）。
- **主 Agent 的五阶段工艺手册不存在**：旧 `bid-master` skill 已退役，其 RETIRED.md 写"承接 → 迁移至 `skills/bid-master/` 时启用"，而该目录**至今未创建**（`skills/README.md` 自标 W3 待办）。
- 即：**唯一承担语义主链路（解构/规格单/关键件/价格）的角色，目前没有工艺书**。

#### A6 ⚠️ 文档真相源已分叉

| 文档 | 声称版本 | 与事实关系 |
|---|---|---|
| `README.md` | v0.3.2（PRD v5.2） | 已过时（含"11 命令表"等旧内容） |
| `docs/plan-baw-implementation.md` | v0.4.0 | 与 DEV_LOG 不符 |
| `DEV_LOG.md` | v0.5.0（最新 DEV-0018） | 与实现一致 |
| `AGENTS.md` | truth layer 唯一事实源 | 与 `docs/prd-baw-v6.md` §1"唯一事实源在 `~/.bidmaster/`（文件）"**措辞冲突** |
| `docs/data-plane-protocol.md` | bids.jsonl 的 stage 唯一写者 | 与 v0.5.0 改道 store.py 冲突 |

**仓库熵**：根目录 19 个日期化 HTML + 6 个 md + `reports/` 21 个日期化 md + `log/` 5 个 —— 全部进 Git，无 `docs/archive/` 分层，无"现行/历史"边界。

### 3.2 业务流层

#### B1 ⛔ 电网没通电：cron 未安装

`crontab -l` 为空。设计 §9 的"一天节奏"（08:30 预警 → 09:00 digest → 10:00 抓取 → 10:05 scout）**全部不在运行**。backlog A2 记着"装机待 owner"，但系统已被宣称为"周期性醒着"。
**后果**：商机池不会自然增长（`leads` 表 55 条是 legacy 期数据）；digest/告警是死数据。

#### B2 ⛔ 关键路径的真实数据为零

| 实体 | 表/目录 | 实测 |
|---|---|---|
| 阶段产物登记 | truth.db.artifacts | **0** |
| 教训 | truth.db.lessons | **0**（lessons.md 有 L-1~L-10 文本，但未入表） |
| 工单 | truth.db.tickets | **0**（queue/ 有 3 个 json 文件，未入表） |
| 归档提案 | `bids/*/archive/proposal.json` | **0 个** |
| locator 报告 | `bids/*/verify/locator-report.json` | **0 个** |
| 门禁历史 | truth.db.stage_history | **0 行**（bids 表存在但历史为空 → 说明 3 个 real 标是**导入/直写**而来，非门禁推进而来） |

**这条最致命**：系统的"飞轮"（S8→S9 强制度量、教训回流、工单闭环）**从未在真实标上运转过一次**。

#### B3 ⚠️ 工单闭环依赖人工且不可观测

设计 D13/§11 明确"一期人肉复制"，但：
- `ticket.generate/list/reconcile` 只有 CLI（`rules/ticket.py`），**未注册为看板命令**（PRD v6 §4 要求）；
- "复制"这一动作无回执，`reconcile` 靠扫文件目录猜；
- 结果：无法回答"哪个工单产出哪些文件、耗时多少、是否完成"。

#### B4 ⚠️ 时间压力不是一等对象

`timeline.json`（答疑截止/保证金/封标/开标）散在各标工作区，无统一聚合与倒计时；PRD §3 的"今日必办"视图未落地。**投标最硬的约束是时间，系统对时间却没有视图。**

#### B5 ⚠️ 资产台账（kb）无入口

`kb/index/{certs,people,cases,solutions}.json` 就位，但：
- `people/certs` 数据未录入（backlog B4'：consistency 无数据可查）；
- 无看板视图（PRD §3"资产台账"未落地）；
- 无"素材缺口"回流（`scoring_skeleton.material_gaps` 产出了但没人消费）。

#### B6 ⚠️ 准入门（lead）与主链路脱节

legacy `leads` 表 55 条 + `lead` 表 1 条 + `~/.bidmaster` 无 leads 目录 → 新老两套商机模型并存；`lead.promote → bid.create` 在新模型（truth.db）上没有对应实现。

### 3.3 功能设计层（对照 PRD v6 §3 七视图）

| PRD 视图 | 现状 | 判定 |
|---|---|---|
| 📊 管线漏斗（S0–S9 数/金额/停留时长） | 首页是 legacy 卡列表（7 条旧标），无漏斗、无金额聚合、无停留时长 | ❌ |
| 🔍 单标深潜 | 无。只有页尾 4 列小表（bid_id/stage/产物数/更新时间） | ❌ |
| ☀️ 今日必办 | 无。仅有"关闭区/digest" | ❌ |
| 🗂 资产台账 | 无 | ❌ |
| 📥 商机 | 有（legacy leads），但非 scout 新链路 | 🟡 |
| 📰 digest | 有（依赖未运行的 cron） | 🟡 |
| ⚙️ 系统（agent 名册/校验通过率/工单/规则变更史） | 无 | ❌ |
| — | 额外：legacy"流程视图/管理视图"（13 步 swimlane 等旧模型）仍然占主导 | 熵 |

**另外两个体验级缺口**：
- **无"AI 运行时"视图**：5 个子智能体的运行记录（run manifest：producer/model/duration/input_fingerprint/ticket_id/self_check）散落在文件，没有表、没有聚合、没有成本视图。目标里"AI 看板"的"AI"部分**在看板上不可见**。
- **无证据反查**：`[P#·章节]「逐字摘录」` 是系统的核心竞争力，但它只存在于文本里，没有结构化，无法"从评分点反查素材/从断言反查原文/看覆盖率"。

### 3.4 工程与治理层

| # | 现象 | 证据 | 后果 |
|---|---|---|---|
| D1 | 门禁只覆盖状态机 | `make gate` = 语法/JSON/agent frontmatter/卫生/20 断言 | BAW 桥接、watcher、PATCH 拦截、命令层**无自动测试** |
| D2 | 主测试套件休眠 | `quality-test.py`（31 项）要求 `:8080` 有服务；服务未运行，且**不在 gate 内** | 回归靠自觉 |
| D3 | 回归基线只有 1 份 | `make regress` 输出"最新 baseline-20260910-w3.json（首份，无对比）"，6 指标比的是自己 | 回归保护是形式 |
| D4 | 无 CI | 只有本地 pre-commit（已安装） | 换机/协作即失效 |
| D5 | 契约无 schema 校验 | 门禁靠 `d.get("result") != "PASS"` 这类弱判断 | 字段改名即静默失效 |

---

## 4. 根因收敛（只有三个）

```
R1 真相源语义未收敛  ──►  5 份副本 / 双数据根 / 文件与 DB 双权威
        │
R2 契约未单点化      ──►  "合格"的定义在写口、门禁、看板各写一遍，且已漂移
        │
R3 看板与生产线是缝合而非同源 ──► legacy 模型 + BAW 模型并存，视图缺席
```

**R1 是根，R2 是干，R3 是叶。** 只修看板（叶）等于把漂移的数据画得更漂亮；必须先修 R1/R2。

---

## 5. 目标架构 v1.0

### 5.1 总图

```
┌─ 契约面（单点）────────────────────────────────────────────┐
│  contracts/artifact/*.schema.json   产物契约（每类产物一份）  │
│  contracts/gates/*.json             门禁规则（声明式）        │
│  contracts/commands/*.json          命令契约（参数/幂等/权限） │
└───────┬──────────────┬──────────────┬─────────────────────┘
        │ 同一份 schema 被三处复用 │
        ▼              ▼              ▼
┌─ 写口 ─────┐  ┌─ 门禁内核 ─┐  ┌─ 看板读模型 ─┐
│ store.py   │  │ evaluate() │  │ read_models  │
│ 唯一写者    │  │ 纯函数      │  │ 只读 SQL 视图 │
└─────┬──────┘  └─────┬──────┘  └──────┬───────┘
      └───────────┬───┴────────────────┘
                  ▼
        ┌─ 真相源 truth.db（唯一权威）──────────────┐
        │ bids / stage_history / gate_attempts      │
        │ artifacts(指纹+status机) / citations      │
        │ tickets / runs / lessons / alerts / config│
        └───────────────┬──────────────────────────┘
                        ▼
              生产层 blobs/bids/<id>/（文件=内容物，登记后才算数）
```

### 5.2 数据面：truth.db 单一权威（对应 R1）

**新增/改造表**：

| 表 | 关键字段 | 作用 |
|---|---|---|
| `bids` | + `title/client_alias/industry/amount_wan/due_at/tier` | 看板漏斗所需字段（不再靠 legacy 库） |
| `stage_history` | 已有 | 状态迁移历史（当前为空 → 必须由推进写入） |
| `gate_attempts` | `bid_id, from, to, ok, blockers(json), ms, ts, actor` | **门禁结构化结果**（看板"卡点面板"直接读） |
| `artifacts` | `bid_id, kind, path, fingerprint, status, producer, manifest_id, registered_at, superseded_by` | 登记制落地；status 由门禁提升 |
| `runs` | `run_id, producer, model, duration_s, input_fingerprint, ticket_id, self_check, tokens, ts` | **AI 可观测**（run manifest 入库，成本视图数据源） |
| `citations` | `bid_id, artifact_id, anchor(page·section), quote, target` | **证据链**（I4：断言语义可反查） |
| `tickets` | 已有 + `prompt_path, artifacts(json), closed_at` | 工单闭环可观测 |
| `leads` | `lead_id, source, url, score, evidence, lifecycle` | 商机统一模型（替代 legacy 双表） |
| `kb_assets` | `domain, id, file, fingerprint, expires_at, sensitive` | 台账从 JSON 索引迁入（**一期必做，P3' 段**——增补件决策 Q3=C 升格） |
| `alerts` / `config` | 告警与参数级配置 | 替代散落 json |

**读模型（消灭镜像）**：
- 看板**不再持有状态**，改为对 `truth.db` 的 **只读连接**（WAL 支持多读单写，进程内直接读，或经 `read_models` 视图函数）。
- 删除 `baw_mirror_*` 表、`projection.db`、`bids.jsonl`（或降级为一次性导出产物，不进决策路径）。
- 遗留 `~/.bidboard/bidboard.db` **冻结只读**，legacy 看板视图下线（或迁为"历史资产"只读页）。

**守护（新增 `rules/reconcile.py`）**：每日 + 每次写后比对 DB ↔ 文件指纹，差异即告警；`make gate` 增加"真相源一致性"检查 → **漂移当天可见**（当前漂移已存在数日无人知）。

### 5.3 契约面：Artifact Contract v2（对应 R2，本方案的核心）

**每条产物一个 schema**，例：

```jsonc
// contracts/artifact/stage0.schema.json（节选）
{ "type":"object",
  "required":["bid_id","positioning","signals","participation","lessons_applied","status"],
  "properties":{
    "status":{"enum":["draft","registered","final","confirmed","superseded"]},
    "lessons_applied":{"type":"array","items":{"pattern":"^L-\\d+$"},"minItems":1},
    "evidence":{"type":"array","items":{"$ref":"#/$defs/citation"}} } }
```

**三处复用的机制**：

| 复用点 | 行为 |
|---|---|
| **写口** `store.register_artifact()` | 按 schema 校验 → 复算指纹 → 落 `artifacts`，`status=registered`；不合格直接拒绝写入 |
| **门禁** `evaluate()` | 只读 `artifacts` 表：该阶段要求的产物 kind 是否 `status=final` 且指纹未变 |
| **看板** | 该产物如何渲染（字段→UI 卡片）由同一 schema 的 `x-ui` 段驱动 |

**收益**：字段改名 → 三处同时红；产物缺失 → 门禁给出**可执行的 hint**（而非"缺文件"）；契约变更可回归（schema diff）。

**配套纪律**：`status` 由门禁提升（`registered → final`），**生产者不得自报 final**（当前 `data/*.json` 无 status、`verify/*.json` 自报 final，两套并存即此问题）。

### 5.4 名门禁内核：声明式规则 + 结构化结果（对应 R2）

```jsonc
// contracts/gates/s3-s4.json
{ "from":"S3","to":"S4",
  "require":[
    {"id":"hits_recon","artifact":"hits_recon","status":"final",
     "check":"all_items_have(收录|排除, reason)","hint":"rules/recon.py --bid {bid}"},
    {"id":"lessons_applied","artifact":"stage0","field":"lessons_applied","check":"all_ids_exist(lessons)"} ] }
```

- `set_stage.py` 退化为**编排器**：读规则 → 调 `rules/gate/evaluate.py`（纯函数，可单测）→ 写 `gate_attempts` → 访问 store 推进。
- 每个失败项输出 `{id, reason, hint, evidence_path}` → 看板卡点面板直接渲染 + 一键复制修复命令。
- 门禁规则纳入 `make gate` 的自检（规则本身可被测试）。

### 5.5 看板：三层注意力模型（对应 R3）

| 层 | 视图 | 数据来源 | 5 秒回答的问题 |
|---|---|---|---|
| **Now** | 今日必办 | `alerts` + `tickets(open)` + `gate_attempts(fail)` + `bids.due_at` 倒计时 | 今天我必须做什么？ |
| **Bid** | 单标深潜（每标一页，替代分散的 dashboard.html） | `bids` + `stage_history` + `gate_attempts` + `artifacts` + `citations` + `runs` | 哪个标有废标风险？AI 产出了什么？ |
| **System** | 系统体检 | `runs` 聚合 + `gate_attempts` 通过率 + tickets 队列 + kb 体检 | AI 干了什么、花了多少、卡在哪？ |

**首页 = Now + 管线漏斗**（S0–S9 各态数量/金额/停留时长）；**legacy 的"流程视图(13 步 swimlane)/管理视图"下线归档**（那是 bid-board 时代模型，与 S0–S9 冲突）。

**每张卡片必须带三样**：阶段 + 门禁通过率 + 下一个待人的动作（Go/No-Go、签核、放行、归档确认）。

### 5.6 服务层拆分（对应 A4）

```
server/            保留 :8080（兼容 PRD §8）
  http.py          HTTP 路由（薄：解析/鉴权/SSE）
  commands.py      命令注册表（契约驱动，含幂等/审计）
  read_models.py   只读查询（漏斗/深潜/今日/系统）
  ingest_watcher.py 文件→登记（改为经 store 登记，而非镜像）
  legacy.py        legacy 只读适配（隔离，随下线删除）
rules/             确定性内核（store / gate / recon / verify / ticket）
```

原则：**HTTP 层不含业务判断**；所有写经 `commands.py → store.py`；所有读经 `read_models.py`。

### 5.7 AI 层（对应 A5/B3/B6）

> **本节由增补件《AI Agent 嵌入层融合方案》（`docs/arch-agent-integration.md`）扩展**：五接触面契约化（触发/输入/产出/知识/观测）——agent 接入契约 `contracts/agents/`、SKILL.md↔contracts 同步（make gate 增 gate-skills）、收割即登记（外部 agent 产物入 artifacts 表带 producer）、工单四态机（回执=runs.ticket_id）、System 层 Agent 运行时面板、llm-wiki 入库（lessons/kb_assets 表权威 + md 渲染层）。下表为原始条目，增补件不推翻、只加严。

| 项 | 动作 |
|---|---|
| 主链路工艺手册 | 补 `skills/bid-master/SKILL.md`（五阶段 + 规格单 + 关键件 + 门禁清单原文）；**这是当前最大空洞** |
| run manifest 入库 | 子智能体/主 Agent 产出后写 `runs` 表（`store.register_run()`），看板系统视图直接聚合 |
| 工单命令化 | `ticket.generate/list/reconcile` 注册为看板命令（PRD §4 补齐），生成即写 `tickets` 表，`reconcile` 按 ticket_id 消单 |
| 传输层可替换 | 一期维持人工复制（人在环），但 `queue/` + `tickets` 表让"已生成/已执行/已消单"三态可见 |
| 子智能体收敛 | 维持 5 个；但明确 **writer/locator/auditor/archivist 的产物必须过 schema**（否则打回），把"信任零假设"从"主 Agent 重跑"改为"**证据可机检**"（成本更低、可观测） |

### 5.8 治理（对应 A6/D1–D5）

1. **文档真相源收敛为 3 份**：`README.md`（现状+入口）、`docs/arch-v1.md`（架构定版，取代 baw-design-v3 + prd-baw-v6 + truth-layer-plan 的冲突段落）、`DEV_LOG.md`（历史）。其余全部移入 `docs/archive/`。
2. **版本单点**：`VERSION` 文件为唯一版本号，README/DEV_LOG/看板页脚读它。
3. **仓库瘦身**：19 个根目录 HTML + `reports/`21 个 md → `docs/archive/{prd,reports}/`；工作区只留现行文档（AGENTS.md 第 7 条纪律的延伸）。
4. **CI 等价物**：`make gate` 增加契约校验/一致性/reconcile/BAW 接口测试；`quality-test.py` 改为可自启 server 或纳入 gate（`make test`）。
5. **契约变更流程**：schema/gate/agent/skill 变更走 .pending → validator → 人确认 → commit（设计 D13 已定，需落地）。

---

## 6. 业务流重构（目标态 S0–S9）

| 阶段 | 人做什么（决策位） | AI/脚本做什么 | 门禁（机检） | 产物契约 |
|---|---|---|---|---|
| S0 线索 | 确认转正 | lead_capture + scout 打分 | evidence 非空、去重 | `lead`（入 DB） |
| S1 预审 | 放行/放弃 | 资质硬条件机检 | certs/people 有效期覆盖 | `precheck.json` |
| S2 决策 | Go/No-Go **签名** | 阶段 0 商机评估 | `lessons_applied` 有效 ID | `stage0.json` |
| S3 解构 | 抽查 20 条 | 主 Agent 单上下文解构 | **hits 对账 100%** | `hits_recon.json` + `response_matrix.json` |
| S4 编制 | 素材确认 | writer 分章 + verify_draft | 完整性 + 评分点覆盖 + 素材匹配率 | `completeness.json` + `spec.json` |
| S5 审查 | 处理阻断项 | auditor 对抗 + locator 抽查 | 阻断=0 + hit_rate≥95% | `audit-rN.json` + `locator-report.json` |
| S6 封标 | **签核放行（L3）** | 渲染 docx + 倒计时 | sign_off 强制 | `final_pack/` |
| S7 开标 | 录入结果 | — | — | `result.json` |
| S8 结果 | 复盘输入 | consistency + 归因 | — | `review.json` |
| S9 归档 | **采纳确认** | archivist 提案 + apply_archive | proposal confirmed + 脱敏 0 命中 + supersession | `proposal.json` |

**相对现状的四处关键修正**：
1. 每个阶段的**产物文件名与 schema 固定**（消灭 hits.json vs hits_recon.json 的漂移）；
2. **每个阶段都有人工位**（不止 S6），且签字入库 `gate_attempts.actor`；
3. S7/S8 有产物（当前完全空缺 → 飞轮没有输入）；
4. `citations` 从 S3 起持续累积（证据链跨越全部阶段）。

---

## 7. 功能清单（v1.0 交付定义）

| # | 功能 | 数据来源 | 验收 |
|---|---|---|---|
| F1 | 管线漏斗 | `bids` + `gate_attempts` | S0–S9 各态数量/金额/停留时长；卡点标红 |
| F2 | 单标深潜 | 全表 + 文件 | 阶段条/卡点清单/产物指纹/证据反查/缺陷轮次/成本，一页看完 |
| F3 | 今日必办 | `alerts`+`tickets`+`due_at` | 空数据时显示"今天无事"而非空白 |
| F4 | 门禁卡点面板 | `gate_attempts` | 每条失败带 hint + 一键复制修复命令 |
| F5 | 工单队列 | `tickets` + `queue/` | 生成/已执行/已消单三态，ticket_id 可反查产物 |
| F6 | AI 运行台账 | `runs` | 按 agent/标/月聚合 token、时长、自检通过率 |
| F7 | 证据反查 | `citations` | 评分点→素材→产物→原文锚点，且显示覆盖率 |
| F8 | 资产台账 | `kb/index` | 四域清单 + 到期预警 + 在投占用 |
| F9 | 商机池 | `leads` | scout 评分 + evidence + 拒绝队列（带原因） |
| F10 | digest | digest_stats | 纯数据保底，LLM 可选增强 |

---

## 8. 落地路线（定稿版 · P0–P3 完整开发计划，含融合增补全部任务）

> 决策注入：Q1=B（legacy 合并后删除：数据迁移在 P1、视图下线在 P2）；Q2=C（真实标产物重做：契约 schema 前置 P0-0）；Q3=C+Q6（本轮 = 主件 P0/P1/P2 + 增补全部段；主件 P3 顺延）；Q4=B（不建 agent_registry）；Q5=B+配置驱动（`ingest_register_types`）。
> 节奏纪律：**每期一个独立提交段**（P0/P1/P2/P3' 各一个 merge 点，可独立回退）；每期完成跑 `make gate + make regress` + 期验收项，不过不进下一期。

### P0 · 契约前置 + 止血 + 产出面（≈1.5 天，commit: `v1.0-p0`）

| # | 任务 | 来源 | 验收 |
|---|---|---|---|
| P0-0 | **契约 schema 设计定稿（Q2=C 前置）**：`contracts/artifact/` 6 类 schema（stage0/hits_recon/completeness/spec/audit/locator）+ `contracts/gate-matrix`（§6 表格机读化） | 主件 P1 前移 | schema 评审一次过；gate-matrix 与门禁代码字段一致（人工核） |
| P0-1 | **真实标产物重做（Q2=C）**：主 Agent 按 P0-0 契约把 `2026-GOLD-jishu` 阶段产物**格式重铸**（hits.json→hits_recon.json 等，解构语义不重跑）+ 逐个 `register_artifact` 登记 | Q2 决策 | S3→S4 卡点清单为空（可推进态）；artifacts 表 ≥5 行（GOLD 全产物） |
| P0-2 | 修正 3 个 real 标 stage 来源（bootstrap 留痕 or 补 lessons_applied 重推） | 主件 | truth.db 每个 stage 都有 stage_history 行与 actor |
| P0-3 | 删除/冻结漂移副本：projection.db 重建后停维护、baw_mirror_* 停写、bids.jsonl 标 deprecated | 主件 | `rules/reconcile.py --check` 报 0 漂移 |
| P0-4 | 安装 cron（backlog A2：08:30/09:00/10:00+16:00/02:30） | 主件 | `crontab -l` 4 条；次日 digest/alerts 有产出 |
| P0-5 | 补 `skills/bid-master/SKILL.md` 主链路工艺手册（五阶段+规格单+关键件+**三条融合纪律**：产物落盘即登记/会话结束 register_run/关键件禁派发） | 主件+增补 §3.3 | 主 Agent 有工艺书；完成条件引用 gate-matrix 渲染 |
| P0-6 | **产出面止血（增补）**：`runs` 表建表 + `store.register_run()`；ingest 收割即登记（`ingest_register_types` 配置驱动，初值 tender/audit-data/checklist——Q5）；ticket.reconcile 回执改查 `runs.ticket_id`（不再扫目录） | 增补 P0 段 | 外部收割的投标相关件在 artifacts 表可见（producer=lingxi-claw 等）；reconcile 查表演示 |

### P1 · 契约收敛 + agent 接入契约（≈3 天，commit: `v1.0-p1`）—— **✅ 2026-09-11 完成**

| # | 任务 | 来源 | 验收 | 状态 |
|---|---|---|---|---|
| P1-1 | Artifact Contract v2 写口校验：register_artifact 按 schema 校验→指纹复算→落库；不合格拒绝写入 | 主件 | 构造缺字段产物被拒（单测） | ✅ |
| P1-2 | 门禁改读 `artifacts` 表（kind+status+指纹未变），不再看裸文件；`artifacts.status` 状态机（registered→final 由门禁提升） | 主件 | 自报 final 被降级；篡改后提升被拒 | ✅ |
| P1-3 | `gate_attempts` 表 + 声明式 gate 规则（contracts/gates/gates.json）+ 结构化卡点 | 主件 | 门禁规则本身可测试（gate-tests 扩展） | ✅ |
| P1-4 | `rules/reconcile.py` + 挂 `make gate`（gate-truth：DB↔文件指纹） | 主件 | 漂移当天红 | ✅ |
| P1-5 | **agent 接入契约（增补）**：`contracts/agents/` ×6 + make gate 增 `gate-skills` + SKILL 完成条件改渲染引用 | 增补 P1 段 | 契约/门禁/skill 任一改动其余两处 gate 红 | ✅ |
| P1-6 | **legacy 数据迁移（Q1=B 前半）**：7 旧标 + 55 线索迁入 truth.db；迁移对账 0 差异；期间冻结只读 | Q1 决策 | truth.db 含 legacy 标（kind=real，来源标注 legacy_migrated）；对账 0 差异 | ✅ |
| P1-7 | 工单四态机：tickets 表 + dispatched_at + `ticket.generate/list/reconcile` 注册为看板命令 | 增补 | 工单生成→消单全程查表可答 | ✅ |

**期验收**：真实标 S3→S4 **一条命令推进成功**（2026-09-11 实测：`set_stage --to S4` coverage=100%，S3→S4）；`make gate` 含契约/一致性/skill 同步三类检查（gate-truth/gate-skills）；门禁失败项 100% 带 hint。

### P2 · 看板重构 + Agent 面板 + 一致性协议（≈4 天，commit: `v1.0-p2`）—— **🟡 2026-09-11 核心完成（P2-1 全量拆分与 legacy 视图下线收敛至 v0.6）**

| # | 任务 | 来源 | 验收 | 状态 |
|---|---|---|---|---|
| P2-1 | server 拆分：http/commands/read_models/watcher/legacy 五模块（HTTP 层零业务判断；写全经 commands→store，读全经 read_models） | 主件 | 单测可覆盖各模块；do_GET if-eli 链消亡 | 🟡 本期落地：read_models.py（读模型全量）+ commands 注册（advance_stage/ticket×3）+ watcher（epoch 轻询）；http/commands 文件级拆分与 legacy.py 隔离收敛 v0.6（3058 行单体一次拆净风险过高，按"薄桥接+读模型"过渡，边界已圈定） |
| P2-2 | **前后端一致性协议四层（增补 §5.3）**：meta.epoch 变更传播（进程内即时/进程外 ≤2s）+ SSE 带 epoch + gate-readmodels + 前端 fail-visible + 禁乐观更新（命令响应即真相） | 增补 | 任何写入 ≤2s 看板可见；后端改字段 gate 红 | ✅ epoch 递增于每次门禁尝试（record_gate_attempt）；/api/baw/epoch 轻询 + 前端比对；契约层 = read_models 返回结构与 read_bid_detail 断言（gate-tests 覆盖） |
| P2-3 | Now / Bid / System 三层视图（F1 漏斗/F2 深潜/F3 今日必办/F4 卡点面板） | 主件 | 首页 5 秒回答三问 | ✅ 读模型 + /api/views/* + 面板四标签实测 |
| P2-4 | **Agent 运行时面板（增补 F6a/F6b）**：名册（直读 contracts/agents，Q4=B）+ runs 聚合（次数/token/时长/自检通过率）+ 工单三态流 + 门禁通过率 TopN | 增补 | 首页 5 秒回答第四问："AI 干了什么、花了多少？" | ✅ System 标签实测（名册/runs 聚合/gate 统计/工单三态） |
| P2-5 | Now 层 agent 卡点（gate_attempts 失败/tickets 超时入必办）+ 深潜证据带 producer/run_id（citations 表本期建表留位，采集在顺延的主件 P3） | 增补 | 被拦瞬间卡点面板可见 | ✅ gate_attempts 失败入 Now（带 blockers 明细）；深潜带 producer/status；citations 表留位（主件 P3 采集） |
| P2-6 | **legacy 视图下线（Q1=B 后半）**：13 步流程视图/管理视图移 docs/archive，SPA 模块化；SSE 事件补 gate/ticket/run/artifact 四类 | Q1+主件 | legacy 模型不再出现在任何决策路径 | 🟡 数据侧完成（legacy 迁移+冻结），视图下线收敛 v0.6（与 P2-1 拆分同批） |

**期验收**：🟡 **实质达成**——四问经 /api/views/* 全答（Now 20 条/漏斗/深潜/Agent 运行时），写入 ≤2s 可见（epoch 实测）；"首页 5 秒"的 UI 呈现随 P2-1 收尾一并完成（面板已可用，legacy 首页替换为 v0.6 收官项）。

### P3' · 知识面入库（≈1 天，commit: `v1.0-p3k`）

| # | 任务 | 来源 | 验收 |
|---|---|---|---|
| P3'-1 | `kb_assets` 一期：certs/people/cases/solutions 四域迁表（JSON 索引降为导出渲染）；consistency.py 改读表 | 增补 P3 段 | 台账告警来自 DB；kb/index 为导出物 |
| P3'-2 | `lessons` 表权威化：apply_archive 改写表（SQL 参数绑定走 store）→ 自动导出 lessons.md；S2→S3 门禁改读表 | 增补 P3 段 | 归档→表→渲染→门禁读表全链可机检（飞轮闭环 DB 事实） |
| P3'-3 | 衰减 cron：每日扫描"超 1 年未引用且被取代"教训置归档、kb_assets expires_at 到期告警 | 增补 P3 段 | 衰减任务进 crontab 且有首日产出 |

### 顺延下轮（主件 P3 · 飞轮与度量，预告）

citations 采集与反查实装（F7 数据源）/ runs 成本月度聚合深化 / `make regress` 第 2 份基线 / 一天全链路演练（backlog A3）/ 商机池新链路（leads 表 + lead.promote 对接 truth.db）。依赖关系：citations 采集依赖 P2-5 的表位；第 2 基线依赖真实标全链路跑通（P1 验收后即具备）。

---

## 9. 风险与取舍

| 风险 | 等级 | 处置 |
|---|---|---|
| 重构期看板不可用 | 中 | P0/P1 不动 UI；P2 用分支 + 旧版保留到新版验收 |
| ~~契约收紧导致真实标更推不动~~ | 已消解 | Q2=C 产物重做：契约先行（P0-0）+ 产物按新契约重铸（P0-1），不存在"让步/收紧"两难 |
| 单人时间不足（≈9–10 天） | **高** | 严格 P0→P3' 顺序 + 每期独立提交段（可回退到任一期）；任一期中断，已完成期价值独立成立 |
| 契约 schema 评审返工（Q2=C 的连锁风险） | 中 | P0-0 单独先行评审一次过再动产物；schema 变更走提案流 |
| SQLite 单文件损坏 | 低 | WAL + 每日 `VACUUM INTO` 备份 + reconcile 校验 |
| 语义质量下降（auditor Flash 稳定性） | 中 | 维持"LLM ∪ 机检"组合判定（已定版），把机检覆盖率作为主指标 |
| 过度设计（引入框架/队列/向量库） | 中 | **明确不做**：RAG/向量检索、消息队列、微服务、多用户鉴权、LLM 编排框架。约束：单机、单人、stdlib 优先 |

**明确不做（与 PRD §10 一致）**：合同/交付/回款段、飞书 Bot/移动端、直接拉起 ZCode 会话。

---

## 10. P0 开工首日清单（对应 §8 P0，按序执行）

1. `contracts/artifact/` 6 类 schema + gate-matrix（P0-0，纯设计物零代码风险，评审一次过）；
2. `rules/reconcile.py`（60 行）：比对 truth.db / jsonl / projection / mirror，输出漂移清单 → 立刻暴露已存在的漂移（P0-3 前置探针）；
3. truth.db 建 `gate_attempts` + `runs` 两张表，set_stage 写 gate_attempts（P1-3 预埋，新表不动老逻辑）；
4. 真实标产物重做（P0-1：主 Agent 会话按契约重铸 GOLD 产物 + 登记）；
5. `skills/bid-master/SKILL.md` 骨架 + ingest 收割即登记 + cron 安装（P0-4/5/6）。

---

## 11. 决策结果（全部已决，2026-09-11）

| # | 决策 | 结论 | 落点 |
|---|---|---|---|
| Q1 | legacy 看板处置 | **B 合并进 truth.db 后删除** | 数据迁移 P1-6 / 视图下线 P2-6 |
| Q2 | 门禁 vs 真实标 | **C 真实标产物重做** | 契约前置 P0-0 / 重铸登记 P0-1 |
| Q3 | 本轮范围 | **C 一路到 P2**（+增补 P3' 知识面） | §8 定稿计划；主件 P3 顺延 |
| Q4 | agent_registry | **B 不建** | System 面板直读 contracts/agents（P2-4） |
| Q5 | 收割登记粒度 | **B 投标相关件 + 配置驱动预留扩展** | `ingest_register_types` 配置（P0-6） |
| Q6 | 融合增补并入 | **全部并入** | P0-6 / P1-5 / P2-2·4·5 / P3' |

---

## 附录 A · 现状体检表（一页速览）

| 维度 | 指标 | 值 | 判定 |
|---|---|---|---|
| 真相源 | truth.db bids / artifacts / lessons / tickets / stage_history | 3 / 0 / 0 / 0 / 0 | ⛔ 登记与历史为空 |
| 副本一致性 | 5 份状态副本 | 已实测漂移 | ⛔ |
| 契约 | 门禁期望产物 vs 实际产物 | 3 处不一致 | ⛔ |
| 真实标可推进性 | `2026-GOLD-jishu` S3→S4 | 缺全部门禁产物 | ⛔ |
| 自动化 | crontab | 空 | ⛔ |
| 工艺手册 | `skills/bid-master/` | 不存在 | ⛔ |
| 看板 | PRD 七视图 | 约 2.5/7 | ⚠️ |
| 测试 | `make gate` | PASS（24 py/24 json/5 agent/20 断言） | ✅ |
| 回归 | `make regress` | 1 份基线（自比自） | ⚠️ |
| 文档 | 根目录 19 HTML + 6 md；reports/ 21 md | 版本号三处不一致 | ⚠️ |
| 遗留面 | `~/.bidboard` bids/leads/events/cmd | 7 / 55 / 150 / 280 | 待决策 |

## 附录 B · 与既有设计文档的关系

本方案**取代**以下文档中冲突的段落（不删除，移入 `docs/archive/` 并标注被取代）：`docs/baw-design-v3.md` §3/§9（数据流口径）、`docs/prd-baw-v6.md` §1（"唯一事实源在文件"表述）、`docs/truth-layer-plan.md` §3/§4（登记制落地方式）。
**保留有效**：`baw-design-v3.md` 的 D1–D13 决策、§7 可观测性三原则、§10 强制者定义、§13 能力边界实测结论、§14 合规红线 —— 这些是本方案的约束前提，未作改动。
