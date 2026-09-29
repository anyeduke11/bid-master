# 投标看板 v0.3.2 PRD · 个人招投标看板【终稿】

> **产品版本:v0.3.2** · **PRD 迭代号:v5.2 终稿** · 2026-08-14
> 作者:Mavis(MiniMax Agent)
> 协作:Duke · prd-iterative 7 轮澄清 + 三维审查 + v5.1 / v5.2 增量
> 上一版:v5(2026-08-14)· 本版为**唯一 truth**,v5 / v5.1 / v5.2 整合
> 关系:本版 = v5 原文 + v5.1 四项 P1 修改 + v5.2 摘要 Agent+Skill 协作增量
> 对应代码:`/Users/duke/.minimax-agent-cn/projects/bid-board/`(server.py 顶部标记 v0.3.2)
> 文件名:`prd-bid-board-v0_3_2-final-20260814.md`(由 v5_2-final 重命名)

---

## 版本对照

| 维度 | 编号 | 说明 |
|------|------|------|
| **产品对外版本** | **v0.3.2** | 本次发布的稳定版,Duke 对外说"v0.3.2" |
| **PRD 内部迭代** | v5.2 终稿 | 内部演进号,v3 → v4 → v5 → v5.1 → v5.2 |
| **v5.1 增量** | v0.3.2-α | 4 项 P1 修改(摘要按需 / 实时推送 / M3 自动升级 / M4 简化) |
| **v5.2 增量** | v0.3.2-β | 摘要 Agent+Skill 协作(对应 v0.3.2 发布版) |
| 上一产品版 | v0.3.1 | 假设(无对应 PRD,Duke 选定 v0.3.2 为本次号) |
| 下一产品版 | v0.4.0 | P1-完善 完成后(看板 UX + 摘要生成) |

> **说明**:PRD 内部用 v5.x 演进号(便于历史追踪),产品对外用 v0.3.2 semver 风格(便于发布/沟通)。两者**一一对应**。

---

## 第 1 章 · 产品概述与目标

### 1.1 产品定位(一句话)

> **个人招投标看板:Duke 通过 AI Agent(我) + Skill 脚本协作,自动化 + 手动双轨管理网络安全领域的招投标全流程。**

### 1.2 核心目标(3 个,可量化)

| # | 目标 | 量化指标 |
|---|------|---------|
| 1 | **每日 10:30 跑完标讯抓取,Duke 11:00 看到结果** | 抓取耗时 < 5 分钟 · 摘要生成 < 30 秒 · 看板刷新 < 5 秒 |
| 2 | **手动管理为主,自动化辅助,Duke 每天看板操作 < 30 分钟** | 70% 操作手动 · 30% 走 Skill/Agent · 自动跑无需人工触发 |
| 3 | **Skill 跑完结果自动同步看板,数据不丢** | Skill 写文件 → bid-board 5s 内拉取 · 失败不阻塞主流程 · 日志全留痕 |
| 4 (v5.2) | **摘要语义归纳,30 秒看完今日重点** | Agent 做语义归纳 · Skill 做基础统计 · 两者合并落 digest.md + bid.ai_summaries |

### 1.3 成功指标

- **效率指标**:日均看板使用时长 30 分钟以内(比 Excel 时代减少 50%)
- **覆盖指标**:每日 10:30 跑完,11:00 前新增 lead 数 ≥ 行业平均
- **可靠性指标**:服务可用率 ≥ 99%(本地崩溃可重启,数据不丢)
- **演进指标**:3 个月内能用上真实抓取(替换 mock),不需重写架构
- **摘要指标(v5.2)**:Duke 看 digest 平均 ≤ 30 秒,信息密度比原"列表罗列"提升 50%

### 1.4 摘要协作原则(v5.2 新增)

- **Skill 跑基础统计**——抓数据、算分数、跑评分、做清单,纯数据活
- **Agent 做语义归纳**——优先级判断、要点提炼、趋势洞察、决策建议,LLM 该干的
- **两者输出合并**——`~/.bidboard/digests/YYYY-MM-DD.md`(摘要文件)+ `bid.ai_summaries` 数组(关键洞察回写)
- **看板调用 Skill 脚本的两种方式**:
  1. **纯数据走按钮**——看板"▶ 跑 Skill"直接 subprocess 调脚本(无需 Agent 介入)
  2. **需语义分析走 Agent**——Agent 调 Skill 拿原始数据,Agent 归纳后回写

---

## 第 2 章 · 用户画像与场景

### 2.1 用户画像

**Duke**,网络安全行业销售 + 售前 PM:
- 10 年金融行业网络安全经验(前腾讯金融安全团队)
- 客户类型:银行/政府/金融/证券/能源/医疗
- 区域:华南/华北/华东
- 客户分级:大B(战略)/中B/小B/微
- 5 阶段业务流:标讯 → 资质 → 识别 → 投标 → 交付
- 技术栈:零依赖(Python stdlib/bash),不滥用 pip
- 个人 IP:SecNews(微信/小红书/抖音)
- 104 个已装 Skill,bash/python 脚本能力强

### 2.2 核心使用场景(用户故事)

| # | 场景 | 用户故事 | 频率 |
|---|------|---------|------|
| S1 | **晨会前看摘要** | 作为 Duke,我希望在 11:00 前打开看板,30 秒内知道今天哪些新标讯值得跟,哪些可以直接略过 | 每日 1 次 |
| S2 | **细看 lead 列表** | 作为 Duke,我希望在中午饭前 15 分钟看完所有新增 lead,决定哪些升级为 bid,哪些丢弃 | 每日 1 次 |
| S3 | **手动改 bid 状态** | 作为 Duke,我希望在投标过程中点几下就能改 stage/block/priority,不用记命令 | 每日 3-5 次 |
| S4 | **触发临时抓取** | 作为 Duke,我希望在见客户前临时抓某行业/某区域的标讯,1-2 分钟出结果 | 每周 1-2 次 |
| S5 | **Agent 兜底** | 作为 Duke,我希望 Skill 跑挂了 Agent 看上下文重试,Agent 跑了关键摘要我直接信 | 不定期 |
| S6 | **看历史命令** | 作为 Duke,我希望每个 bid 卡片能下拉看历史命令(谁/何时/为什么/参数),方便复盘 | 每周 2-3 次 |
| S7 | **周/月复盘** | 作为 Duke,我希望每周/每月自动出总结(赢率/Top 客户/输单原因),不复盘就不知道趋势 | 每周/每月 |

### 2.3 使用频率与时长预估

| 时段 | 活动 | 时长 |
|------|------|------|
| 08:30 | 晨会,口头过状态 | 15 min |
| 10:30 | cron 触发抓取(无需 Duke 操作) | 0 min |
| 10:35 | 实时推送"今日新增 N,P0:M"(v5.1 改) | 0 min |
| 11:00 | 看板检测当日 digest 不存在则自动生成(按需)(v5.1 改) → Duke 看 digest + 决策 | 5-10 min |
| 12:00 | 午饭前细看 lead 列表 + 升级 | 10-15 min |
| 14:00-18:00 | 客户沟通 + 手动改 bid | 分散 |
| 21:00 | 看今日复盘(可选) | 5 min |

**总看板操作**:约 30 min/天 · 其中 5-10 min 是"主动浏览",20 min 是"沟通中查/改"

---

## 第 3 章 · 功能模块设计

### 3.1 模块总览图

```
┌─────────────────────────────────────────────────────────────┐
│                       bid-board v0.3.2                          │
├──────────────┬──────────────┬──────────────┬────────────────┤
│  看板层 (UI) │ 调度层 (调度) │ 数据层 (DB)  │  集成层 (外部)  │
│              │              │              │                │
│ 📊 看板视图  │ Skill 调用器 │ SQLite       │ ~/.bidboard/   │
│ ⇉ 流程视图  │ Agent Hook   │ - bids       │  leads.jsonl   │
│ 📥 商机视图  │ 文件监听器  │ - lead       │  qualify.jsonl │
│ 📋 今日摘要 │ 摘要生成器   │ - command    │  archive/      │
│ ⚙️ 管理视图  │ 命令注册表   │ - activity   │  digests/      │
│              │              │ - log        │  log.jsonl     │
└──────────────┴──────────────┴────────────────┴────────────────┘
```

### 3.2 模块清单(7 个)

| # | 模块 | 功能 | 输入 | 输出 | 优先级 |
|---|------|------|------|------|--------|
| M1 | **看板 UI** | 3+1 视图(看板/流程/商机/管理)+ 摘要 | 内存 STATE | HTML 渲染 | P0 |
| M2 | **命令注册表** | 11 个注册命令,banner 写操作唯一入口 | commandId + params | result + execution_id | P0 |
| M3 | **文件监听器** | 5s 轮询 `~/.bidboard/*.jsonl`,落 SQLite + **自动升级 P0 lead**(v5.1) | 文件系统 | DB rows + SSE | P0 |
| M4 | **Skill 状态显示**(v5.1 改) | 看板显示 Skill 列表 + 上次运行时间 + 状态;**纯数据按钮可直调脚本**(v5.2) | UI 点击 / 状态读取 | 状态渲染 / 脚本执行 | P0 |
| M5 | **Agent Hook** | `~/.bidboard/agent_queue/` 文件队列,Agent 处理 | 用户/系统触发 | 写回 bid.ai_summary 字段 | P0 |
| M6 | **摘要生成器** | **按需生成**(v5.1 改)+ **Agent+Skill 协作**(v5.2) | 新 lead 列表 | digest md 文件 | P1 |
| M7 | **管理视图** | 客户数据 / 事件日志 / 剧本 / 总结 4 子 tab | 内存 STATE | 表格渲染 | P1 |

### 3.3 模块依赖关系

```
M1 (UI) ──→ M2 (命令) ──→ SQLite
   │             │
   ├──→ M4 (Skill 状态 + 直调按钮) ──→ ~/.bidboard/  ──→ M3 (监听) ──→ SQLite
   │                                                                 │
   │                                                          (M3 自动升级 P0)
   │                                                                 ↓
   ├──→ M5 (Agent) ──→ M2 (命令) + M1 (UI 刷新)              lead.promote
   │
   ├──→ M6 (摘要 Agent+Skill 协作) ──→ ~/.bidboard/digests/ ──→ M1 (摘要 tab)
   │       │
   │       ├──→ Skill 跑基础统计(数量/分组/Top N)
   │       └──→ Agent 读 Skill 输出 + lead 数据 → 语义归纳
   │
   └──→ M7 (管理) ──→ SQLite(只读)
```

**关键依赖**:
- M3 是数据流的"汇点"——所有 Skill 输出都经过它
- M5 通过 M2 写数据,符合"Agent 必须用命令"原则
- M6 是只读 + 写文件,不动 SQLite(摘要不进事实层)
- M3 自动升级 P0 lead(v5.1):recommend=P0 且 score≥80 自动调 lead.promote,Duke 仍需在商机 tab 确认或丢弃

### 3.4 M6 摘要协作流程(v5.2 新增)

```
需求:今日 11:00 digest
  │
  ├── 11:00 之前 Duke 进看板
  │     │
  │     ├── 看板检测 digests/$(date).md 是否存在
  │     │     │
  │     │     ├── 存在 → 直接渲染,0 等待
  │     │     │
  │     │     └── 不存在 → 触发按需生成
  │     │              │
  │     │              ↓
  │     │     ┌─ 步骤 1:Skill 跑基础统计 ─┐
  │     │     │  • lead 数 / 行业分布 / 金额  │
  │     │     │  • Top 5 客户 / Top 3 标讯  │
  │     │     │  • 输单原因 / 赢率           │
  │     │     │  → 输出到 ~/.bidboard/digests/.tmp/stats.json │
  │     │     └──────────────────────────────┘
  │     │              │
  │     │              ↓
  │     │     ┌─ 步骤 2:Agent 语义归纳 ──────┐
  │     │     │  • 读 stats.json + lead 原始数据  │
  │     │     │  • 优先级判断 / 要点提炼           │
  │     │     │  • 趋势洞察 / 决策建议            │
  │     │     │  → 合并为 digest.md              │
  │     │     │  → 关键洞察调 bid.attach_summary │
  │     │     └─────────────────────────────────┘
  │     │              │
  │     │              ↓
  │     └── digests/YYYY-MM-DD.md + bid.ai_summaries 已就绪
  │
  └── 看板"📋 今日 digest" tab 渲染
       │
       ├── 快读屏:3 条重点 + 行业分布
       └── 详读屏:全部 lead + 完整摘要
```

**协作原则**:
- 纯数据活(数数 / 算分 / 跑列表)走 Skill 脚本,**不绕 Agent**
- 需语义判断(优先级 / 提炼 / 建议)走 Agent,**Agent 调 Skill 拿原始数据**
- 看板直调 Skill 按钮:仅用于"纯数据抓取 / 跑评分",**不用于"做摘要"**(摘要需语义归纳,必须 Agent)

---

## 第 4 章 · 系统架构设计

### 4.1 技术栈

| 层 | 选型 | 理由 |
|---|------|------|
| 后端 | Python 3 stdlib(http.server, sqlite3, json, subprocess) | 零外部依赖,Duke 偏好 |
| 前端 | 单 HTML + 原生 JS(无框架) | 轻量,SPA 单页 |
| 数据库 | SQLite WAL 模式 | 本地嵌入式,事务支持 |
| 外部存储 | `~/.bidboard/*.jsonl` 文件 | Skill 输出的"中转站" |
| 调度 | cron + Python threading.Timer | 本地无外部调度器 |
| 通信 | HTTP API + SSE | 实时推送,跨 tab 同步 |
| 摘要协作 | Skill 脚本(基础统计) + Mavis Agent(语义归纳) | v5.2 双角色分工 |

### 4.2 文件结构

```
~/.minimax-agent-cn/projects/bid-board/
├── server.py                # 主服务 · 84KB · 11 命令
├── public/
│   └── index.html           # SPA · 1100+ 行 · 4 视图(看板/流程/商机/管理/摘要)
├── scripts/                 # ★ Skill 脚本(本地优先)
│   ├── lead_capture.sh      # L1 标讯抓取(直接 curl,写文件,不走 bid-board)
│   ├── qualify_score.py     # L2 评分
│   ├── digest_stats.py      # ★ 新:M6 摘要基础统计(纯数据,不归纳)
│   ├── bid_*.sh             # L3 投标剧本
│   ├── delivery_extract.py  # L4 合同抽取
│   └── archive_close.py     # L5 归档
├── channels.json            # 抓取渠道配置(10 个)
├── start.sh / stop.sh       # 启停脚本(含 cron 10:30)
├── quality-test.py          # 31 项自动化测试
└── README.md

~/.bidboard/                  # ★ 数据持久化
├── bidboard.db             # SQLite(WAL)· 6 表
├── log.jsonl                # 模块化日志
├── leads.jsonl              # L1 标讯落盘(Skill 写)
├── qualify.jsonl            # L2 评分落盘
├── archive/                 # L5 归档(按季度)
│   └── 2026-Q3.jsonl
├── digests/                 # ★ M6 摘要输出
│   ├── 2026-08-14.md        # 终稿(Agent 写)
│   └── .tmp/stats.json      # 步骤 1 中间产物(Skill 写)
├── agent_queue/             # M5 Agent 队列
│   └── req_xxx.json
└── lark_config.json         # 飞书 webhook(可选)
```

### 4.3 数据层设计(6 表 + 4 文件)

**SQLite 表**(v4 已建):
- `bids` (含 ltc_stage/ai_summaries/lifecycle_history 字段)
- `events` (兼容)
- `leads` (兼容)
- `archive` (兼容)
- `command_execution` (审计,11 命令)
- `activity_log` (活动日志)

**文件**(M3 监听):
- `leads.jsonl` — Skill 写入,banner 拉取入库
- `qualify.jsonl` — Skill 写入
- `archive/*.jsonl` — Skill 写入
- `digests/YYYY-MM-DD.md` — M6 Agent 写入(终稿)
- `digests/.tmp/stats.json` — M6 步骤 1 中间产物(Skill 写入)

### 4.4 外部依赖

- **网络**:Skill 抓取时访问外网(标讯源)· 平时无需联网
- **文件锁**:SQLite WAL 多连接安全
- **进程**:Service (`start.sh` 启动) + 可选 cron
- **Agent**:Mavis/MiniMax 进程需在跑(摘要协作),不在则 digest 只生成 stats.json 不出 md

---

## 第 5 章 · 业务流分析

### 5.1 核心业务流(7 个场景)

#### 场景 S1:每日 10:30 自动抓取 + 实时推送 + 按需摘要(v5.1 改)

```
08:30  Duke 晨会
10:30  Python threading.Timer 触发 lead_capture.sh
       ↓
       Skill 直接 curl 10 个渠道,绕过 bid-board
       ↓
       写 ~/.bidboard/leads.jsonl
       ↓
10:35  M3 监听器(5s 轮询)检测文件变更
       ↓
       入库 SQLite(去重,已存在的 lead 跳过)
       ↓
       SSE 推 bid_created 事件 + 实时推送 toast "今日新增 N 条 P0:M"
       ↓
       M3 自动升级(v5.1):recommend=P0 且 score≥80 的 lead
       ↓
       自动调 lead.promote(D 仍需在商机 tab 确认或丢弃)
       ↓
       看板"📥 商机"tab 实时显示新 lead
       │
       │  11:00 之前
       ↓
11:00  Duke 进看板
       │
       ├── 看板检测 digests/$(date).md 是否存在
       │     │
       │     ├── 存在 → 直接渲染 digest(0 等待)
       │     │
       │     └── 不存在 → 触发按需生成(v5.1 改)
       │              │
       │              ├─ 步骤 1:Skill 跑 digest_stats.py
       │              │   → ~/.bidboard/digests/.tmp/stats.json
       │              │
       │              └─ 步骤 2:Agent 语义归纳
       │                  → ~/.bidboard/digests/2026-08-14.md
       │                  → 关键洞察调 bid.attach_summary
       ↓
       "📋 今日 digest"tab 显示快读(3 条重点)+ 详读(全部)
       ↓
       Duke 30 秒看完,决定哪些 lead 升级 / 哪些丢
```

#### 场景 S2:Agent 对话触发(临时专项)

```
14:00  Duke:"今天银行行业有什么新标讯?"
14:00  Agent 理解意图,执行 bid-news-collection --industry=银行
       ↓
       Skill 跑,写文件
       ↓
       M3 监听入库
       ↓
       Agent 读新 lead,给 Duke 摘要
14:02  Duke 看到 3 条银行标讯,点开详情,升级 1 条
```

#### 场景 S3:手动跑 Skill(v5.1 简化为状态显示 + v5.2 直调能力)

```
15:00  Duke 准备见某客户,临时抓"广发银行 + 零信任"
15:00  Duke 在看板"📊 看板视图"顶部看到 Skill 状态卡(显示 lead_capture.sh 上次跑 10:30,状态 ok)
15:00  Duke 不想等下次 cron,点"▶ 立即跑"按钮(v5.2 允许纯数据直调)
       │
       ├── 走 Skill(纯数据) → 看板 M4 直接 subprocess 调 lead_capture_custom.sh
       │     ↓
       │   脚本跑完,写文件
       │     ↓
       │   M3 监听入库
       │     ↓
       │   看板刷新,新 lead 出现
       │
       └── 需语义分析 → Duke 走 Agent 对话(场景 S2)
15:02  Duke 看到 1 条新 lead,准备就绪
```

> **v5.1 修订说明**:M4 从"跑 Skill 按钮 + 复杂对话框"简化为"Skill 状态显示 + 立即跑按钮(纯数据)";不再要求 Duke 配置复杂参数,推荐 cron 跑。

#### 场景 S4:Duke 手动改 bid 状态(主要操作,70%)

```
10:00  Duke 在跟客户沟通:"进入修订阶段"
10:00  Duke 在看板点"修订"按钮
       ↓
       看板 M1 弹出"命令面板"(M2)
       ↓
       Duke 填 reason + 选 evidence
       ↓
       看板 POST /api/commands {commandId:"bid.update_field", params:{...}}
       ↓
       M2 事务化执行:DB + activity_log + command_execution
       ↓
       SSE 推 bid_updated
       ↓
       看板卡片自动更新
```

#### 场景 S5:Agent 摘要(摘要能力)

```
12:00  Duke 看到 5 条 lead,想升级 2 条
12:00  Duke 点"🤖 AI 摘要" 按钮(2 次)
       ↓
       看板 M1 → M5:写 ~/.bidboard/agent_queue/req_001.json,req_002.json
       ↓
       Agent 看到队列(下次对话)
       ↓
       Agent 读 bid 数据 + 行业上下文
       ↓
       Agent 调 M2:POST /api/commands bid.attach_summary
       ↓
       bid.ai_summaries 数组追加
       ↓
       看板"🤖 Mavis 摘要"显示
```

#### 场景 S6:lead 升级为 bid(决策点)

```
11:30  Duke 看完 lead,决定升级 1 条
       │
       ├── 手动升级
       │     Duke 点"升级为 bid"按钮
       │     ↓
       │     看板 M1 → M2:POST /api/commands lead.promote
       │     ↓
       │     M2 在事务内:
       │       1. SELECT lead
       │       2. _create_bid(从 lead 字段,ltc_stage=opportunity)
       │       3. UPDATE lead.lifecycle=promoted
       │     ↓
       │     SSE 推 bid_created + lead_updated
       │     ↓
       │     看板"📊 看板视图"和"📥 商机视图"同步更新
       │
       └── M3 自动升级(v5.1 新增)
             recommend=P0 且 score≥80 的 lead 入库时自动调 lead.promote
             ↓
             lead.lifecycle=promoted_peding_confirm(待确认)
             ↓
             Duke 在商机 tab 看到"已自动升级 X 条(待确认)"
             ↓
             Duke 一键确认或丢弃
```

#### 场景 S7:周/月复盘

```
周日 20:00  Duke 主动点"📊 周报"按钮
       ↓
       看板读 SQLite 聚合
       ↓
       展示:
         - 本周新增 N / 推进 M / 中标 K / 流失 L
         - 行业 / 区域 / 分级分布
         - Top 5 客户
         - 输单原因聚合
```

### 5.2 异常流处理

| 异常 | 检测 | 处理 |
|------|------|------|
| Skill 跑超时(>30s) | subprocess timeout | 写 `~/.bidboard/leads.jsonl` 半成品 + 标记 failed · 看板 toast |
| Skill 跑挂(非零退出) | subprocess returncode | 写错误到 log.jsonl · 不入 leads.jsonl · 看板 toast |
| 文件监听器漏读 | 5s 轮询 + mtime 检查 | 下次轮询补上 · 幂等去重 |
| Agent 不在线(摘要没做) | 队列里有 req_xxx.json | Duke 可手动触发 · 看板显示"待 Agent 处理" · digest 只生成 stats.json |
| digest 步骤 1 失败 | Skill 跑挂 | 用昨日 digest 兜底 · 看板显示"今日 digest 待补" |
| digest 步骤 2 失败 | Agent 离线 | digest 只到 stats.json · 看板显示 stats(纯数据视图) |
| bid-board 服务挂 | Duke 看到 502/timeout | start.sh 重启 · SQLite 持久化,数据不丢 |
| SQLite 锁 | busy_timeout=15s | 自动重试 · 日志记 timeout |
| M3 自动升级误判(v5.1) | recommend=P0 但实际不该升 | lead.lifecycle=promoted_pending_confirm · Duke 一键丢弃回滚 |

### 5.3 模块联动逻辑

```
Skill 写文件
  ↓ 文件系统事件
M3 监听器
  ↓ SQLite INSERT
bids / lead 表
  ↓ M3 自动升级 P0 lead(v5.1)
  ↓ lead.promote
bids / lead.lifecycle=promoted_pending_confirm
  ↓ SSE broadcast
M1 看板 UI 实时刷新
  │
  ├── 11:00 之前 Duke 进看板
  │     ↓
  │   看板检测 digests/$(date).md
  │     ↓
  │   按需触发 M6 摘要协作
  │     │
  │     ├── Skill 跑 digest_stats.py
  │     │     ↓
  │     │   stats.json
  │     │
  │     └── Agent 读 stats.json + lead
  │           ↓
  │           digest.md
  │           ↓ bid.attach_summary
  │           bid.ai_summaries
  │
  └── 看板"📋 今日 digest" tab 显示
```

---

## 第 6 章 · 操作流分析

### 6.1 日常操作流(用户视角)

```
10:30  (系统自动)  Skill 跑,数据入看板
10:35  (系统自动)  M3 实时推送 toast "今日新增 N,P0:M"
11:00  Duke 打开看板
        1. 看板首页"📋 今日 digest"摘要卡片
           (若不存在,按需生成,5-10s 后就绪)
        2. 30 秒扫 digest 重点(3 条)+ 看行业分布
        3. 切换到"📥 商机" tab
           (含 M3 自动升级待确认的 lead)
        4. 对感兴趣的 lead 点"🤖 AI 摘要"或直接"升级为 bid"
        5. 升级后切换到"📊 看板" tab,新 bid 卡片在第一行
14:00  客户沟通中,Duke 边说边改 stage
        1. 在 bid 卡片上点"修订"按钮
        2. 命令面板弹出,填 reason
        3. 卡片自动更新
17:00  Duke 见完客户,标记 close
        1. 卡片"✓ 关闭"按钮 → 命令面板
        2. 填 outcome=win / loss + 输单原因
        3. 卡片显示"中标"/"丢标" + 归档倒计时
```

### 6.2 周期性操作流

| 周期 | 触发 | 操作 | 输出 |
|------|------|------|------|
| **每日 10:30** | cron | lead_capture.sh 跑 | leads.jsonl · 实时推送 toast |
| **每日 11:00 前(按需)** | 进看板检测 | 缺失则触发 M6 协作 | digest.md |
| **每周日 20:00** | cron | weekly_summary | 周报 HTML |
| **每月 1 日 09:00** | cron | monthly_summary | 月报 HTML |
| **每季度 1 日** | cron | quarterly_summary | 季报 HTML |
| **每年 1 月 1 日** | cron | yearly_summary | 年报 HTML |
| **30 天自动** | _auto_archive_check | closed → archived | lifecycle=archived |

### 6.3 自动化操作流(无需人工)

| 任务 | 触发 | 频率 | 备注 |
|------|------|------|------|
| lead_capture | cron | 每日 10:30 | 主抓取路径 |
| file_watcher | threading.Timer | 每 5s | 监听 `~/.bidboard/*.jsonl` |
| auto_promote(v5.1) | M3 监听 | 实时 | recommend=P0 + score≥80 自动升级 |
| auto_archive | 启动时 | 一次性 | closed 30 天 → archived |
| activity_pause | 启动时 | 一次性 | active 90 天无 sync → paused |
| digest_on_demand(v5.1) | 进看板检测 | 每日 1 次 | 缺失则触发 M6 协作 |
| weekly_summary | cron | 周日 20:00 | 看板"周报"tab |

---

## 第 7 章 · 数据模型设计

### 7.1 核心实体(7 个)

#### 实体 1:bid(主表)
```python
{
  "code": "dgyhst2026",          # PK,投标编号
  "client": "东莞银行",          # 客户名
  "stage": "修订",               # 阶段
  "priority": "P0",             # P0/P1/P2
  "due_at": "2026-08-13 17:00",  # 截止时间
  "ai_ready": [...],             # AI 完成项
  "human_todo": [...],           # 人工待办
  "block": "",                   # 阻塞原因
  "lifecycle": "active",         # active/paused/closed/archived
  "ltc_stage": "bid",            # v4: lead/opportunity/quotation/contract/delivery
  "ai_summaries": "[{...}]",     # v4: AI 摘要数组
  "lifecycle_history": "[...]"   # v4: 状态机历史
  "tier": "大B",                 # 业务维度
  "industry": "银行",
  "region": "华南",
  "est_amount": 280,             # 预计金额(万)
  "decision_maker": "张行长",
  "competitors": ["绿盟", "启明"],
  "loss_reason": "",             # 输单原因
  "last_sync": "2026-08-14 10:35",
  "created_at": "2026-07-15 09:30",
  "updated_at": "2026-08-14 11:00",
  "closed_at": "", "archived_at": "",
  "flow": { "blocked_node": null, "nodes": [...] }
}
```

#### 实体 2:lead(v4 新加)
```python
{
  "lead_id": "lead_2026-08-14_001",  # PK
  "title": "...", "buyer": "...", "industry": "...", "region": "...",
  "amount": 280, "deadline": "...", "source": "...", "run_id": "...",
  "score": 75, "recommend": "P0", "reason": "...",
  "lifecycle": "new",  # new/reviewed/qualified/promoted/discarded/promoted_pending_confirm
  "promoted_to_bid": "dgyhst2026",  # 升级后的 bid
  "raw_payload": "...",
  "created_at": "...", "updated_at": "..."
}
```

**lifecycle 状态机**(v5.1 扩展):
```
new → reviewed → qualified → promoted (M2 手动)
                              └→ promoted_pending_confirm (M3 自动,需 Duke 确认)
                              └→ discarded
```

#### 实体 3:command_execution(v4 审计)
```python
{
  "execution_id": "cmd_1786685065592_7328",
  "commandId": "bid.update_field",
  "idempotency_key": "test-idem-001",
  "payload_hash": "hash-X",
  "agent_id": "duke",
  "params": "...",
  "result": "...",
  "status": "completed",  # processing/completed/failed
  "error": "",
  "created_at": "...", "completed_at": "..."
}
```

#### 实体 4:activity_log(v4)
```python
{ "ts": "...", "actor": "duke|mavis|system", "action": "...",
  "target_type": "bid|lead|flow_node", "target_id": "...", "payload": "...",
  "execution_id": "cmd_..." }
```

#### 实体 5:collection_run(v4)
```python
{ "run_id": "run_2026-08-14_001", "source": "...", "channel_name": "...",
  "status": "applied|rejected|pending_review|partially_applied",
  "items_count": 5, "applied_count": 4, "rejected_count": 1,
  "started_at": "...", "completed_at": "...",
  "payload_hash": "..." }
```

#### 实体 6:leads.jsonl(文件,Skill 写)
```json
{"ts":"...","title":"...","buyer":"...","industry":"...","region":"...","amount":280,"deadline":"...","source":"...","link":"...","raw_keywords":"..."}
```

#### 实体 7:digests/YYYY-MM-DD.md(文件,M6 Agent+Skill 协作写,v5.2 升级)

```markdown
# 2026-08-14 标讯 digest

> 生成方式:M6 Agent+Skill 协作(v5.2)
> 步骤 1:Skill 跑 digest_stats.py → stats.json
> 步骤 2:Agent 读 stats.json + lead → 语义归纳 → 本文件 + bid.ai_summaries

## 今日重点(3 条 · Agent 归纳)
- 某股份制银行 2026 数据安全态势感知项目 480 万(银行 / P0 · 评分 92)
- 某省政务云等保 2.0 三级建设项目 320 万(政府 / P0 · 评分 88)
- 某券商网络安全防护升级 180 万(证券 / P1 · 评分 78)

## 行业分布(Skill 统计)
- 银行:5 (2 P0) · 政府:3 (1 P0) · 证券:2 · 能源:1 · 医疗:1

## 金额 Top 5(Skill 统计)
- 480 万 · 某股份制银行 数据安全
- 320 万 · 某省政务云 等保
- ...

## Agent 建议
- 优先跟进:某银行零信任(标的 580 万,银行大B,本周截止)
- 关注:政府等保项目集中爆发,可能多家客户在做预算
- 风险:某 P0 lead 已自动升级,需 Duke 确认是否符合资质
```

#### 实体 8(v5.2 补充):digests/.tmp/stats.json(中间产物)
```json
{
  "date": "2026-08-14",
  "total_leads": 12,
  "by_industry": {"银行": 5, "政府": 3, "证券": 2, "能源": 1, "医疗": 1},
  "by_priority": {"P0": 3, "P1": 5, "P2": 4},
  "top_by_amount": [...],
  "generated_at": "2026-08-14 11:00:05"
}
```

### 7.2 实体关系

```
collection_run (1) ──< (N) lead
                            ↓ promote (M2 手动 / M3 自动 v5.1)
                            bid (1) ──< (N) command_execution
                            ↑                      ↑
                            activity_log (1) ──< (N) command_execution
                            
                            bid.ai_summaries ←── M6 bid.attach_summary (v5.2)
                            
file ~/.bidboard/leads.jsonl  ──监听──>  lead (M3)
file ~/.bidboard/digests/.tmp/stats.json ──读取──> Agent (M6 步骤 2)
file ~/.bidboard/digests/*.md ──读取──>  UI "今日 digest" (M6)
```

### 7.3 数据流转路径

**路径 1:Skill 自动抓取(主)**
```
渠道(curl) → leads.jsonl → M3 监听 → lead 表 → SSE → UI"商机"
                                         ↓ M3 自动升级 P0(v5.1)
                                       lead.promote → bid 表
```

**路径 2:Agent+Skill 协作摘要(v5.2 升级)**
```
新 lead → M6 步骤 1:Skill digest_stats.py → stats.json
       → M6 步骤 2:Agent 读 stats.json + lead → digest.md
                                      → bid.attach_summary → bid.ai_summaries
       → M1 看板"📋 今日 digest" 渲染
```

**路径 3:手动决策**
```
UI 按钮 → M2 命令注册 → bid 表 + activity_log + command_execution → SSE → UI 更新
```

**路径 4:Agent 写摘要**
```
UI"🤖 AI 摘要" → M5 队列 → Agent 读 bid → M2 bid.attach_summary → bid.ai_summaries
```

**路径 5(v5.1 新增):M3 自动升级**
```
leads.jsonl → M3 监听 → recommend=P0 && score≥80?
                                ↓ 是
                          lead.promote(自动)
                                ↓
                          lead.lifecycle=promoted_pending_confirm
                                ↓
                          Duke 在商机 tab 确认或丢弃
```

---

## 第 8 章 · 开发优先级与里程碑

### 8.1 Phase 划分

| Phase | 主题 | 工期 | 交付物 | 验收 |
|-------|------|------|--------|------|
| **P0-MVP** | Skill 主导核心闭环 | 1 周 | 7 个模块全跑通 | Duke 每日 10:30 抓取,11:00 看 digest |
| **P1-完善** | 看板 UX + 摘要生成 | 1 周 | 商机视图 + digest tab + 命令面板 | 手动 + Skill + Agent 三入口全跑通 |
| **P2-打磨** | 真实抓取 + 数据质量 | 2 周 | 10 渠道真实抓取 + DataQualityTask | 替换 mock,数据可信 |
| **P3-扩展** | 移动端 + 多用户(可选) | - | 响应式 + Lark 推送 | 客户能在手机看 |

### 8.2 P0-MVP 详细(1 周,5 天 · v5.2 修订)

| Day | 任务 | 验收 |
|-----|------|------|
| D1 | 重构 lead_capture.sh(去掉 curl bid-board,只写文件) | 脚本跑完,leads.jsonl 有新行,banner 不被影响 |
| D1 | 实现 M3 文件监听器(5s 轮询 → SQLite) | leads.jsonl 写后 5s 内 lead 表新增 |
| D1 | **M3 自动升级 P0 lead(v5.1)** | recommend=P0 + score≥80 自动 lead.promote,lead.lifecycle=promoted_pending_confirm |
| D2 | 看板新增"📥 商机" tab(展示 lead 列表) | 升级按钮可见,点"升级"触发 lead.promote |
| D2 | **M4 简化为 Skill 状态显示(v5.1)** | 看板显示 Skill 列表 + 上次运行时间 + 状态,"▶ 立即跑"按钮直调(v5.2) |
| D3 | **M6 步骤 1:digest_stats.py(Skill 跑基础统计,v5.2)** | 跑完生成 digests/.tmp/stats.json |
| D3 | **M6 步骤 2:Agent 语义归纳模板(v5.2)** | Agent 读 stats.json + lead → 生成 digest.md + bid.attach_summary |
| D3 | **进看板按需检测 digest(v5.1)** | digests/$(date).md 不存在则自动触发 M6 协作 |
| D4 | 现有 v3/v4 兼容测试 + 文档 | 31/31 质量测试通过 + v5.2 新功能测试 |
| D5 | Duke 真实跑一天,收集反馈 | 实操可用 |

### 8.3 关键依赖

- v3/v4 已落地,11 命令 + SQLite 持久化 · 不重写
- Skill 脚本已存在 6 个(lead_capture/qualify/bid_*/delivery/archive)· 改造
- Agent 队列已实现(agent_queue/)· 复用
- 飞书 webhook 已实现(可选)· 复用
- v5.2 新增:digests/.tmp/ 目录(digest_stats.py 写入)

### 8.4 风险点

- **v4 命令注册**:与 v5 "Skill 主导"可能有冲突(Duke 看板改 bid 还是走命令)
  - 解决:保留 v4 命令注册,Skill 跑完结果"间接"通过 Agent 调命令入库
- **数据一致性**:Skill 写文件 + bid-board 监听入库,中间可能丢
  - 解决:文件 idempotent_key 字段去重 · DB UNIQUE 约束
- **M3 自动升级误判(v5.1)**:recommend=P0 不一定真该升
  - 解决:lead.lifecycle=promoted_pending_confirm · Duke 必须在商机 tab 确认
- **摘要协作 M6 步骤 1 失败**:Skill 跑挂时,Agent 拿不到 stats.json
  - 解决:用昨日 digest 兜底 + 看板显示"今日 digest 待补" + 仅有 stats.json 时降级为纯数据视图
- **Agent 不在线时 M6 步骤 2 失败**:Agent(Mavis)未启动
  - 解决:看板显示"待 Agent 处理" + digest 只到 stats.json + 看板可读 stats 纯数据视图

---

## 第 9 章 · 风险与缓解

### 9.1 技术风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| SQLite WAL 文件损坏 | 低 | 高 | 每日 cron 备份到 `~/.bidboard/backup/` · 损坏时回滚 24h |
| Skill 网络抓取失败(标讯源改版) | 中 | 中 | Skill 失败有 mock 兜底 · Agent 兜底重试 |
| 5s 轮询错过文件变更 | 低 | 低 | mtime 检测 · 启动时全量扫描补漏 |
| 进程崩溃(无限循环) | 中 | 中 | threading.Timer 单次触发 · restart.sh watchdog |
| Python 3.14 兼容(用了未发布 API) | 低 | 高 | 锁版本 pyproject.toml · 已有 stdlib |
| digest_stats.py 脚本 bug | 中 | 中 | 单测覆盖 · 用昨日 digest 兜底 |
| M3 自动升级与人工决策冲突 | 中 | 中 | lead.lifecycle=promoted_pending_confirm · Duke 一键回滚 |

### 9.2 产品风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Duke 10:30 之前不看 digest,过期未用 | 中 | 中 | digest 永久保存 · 看板"昨日"切换 |
| 标讯 mock 数据让 Duke 误判市场 | 高(初期) | 中 | 显眼标注 "[MOCK 数据]" · 快速接真实抓取 |
| 摘要信息密度过高,反而不想看 | 中 | 中 | 摘要分两屏:快读(3 条重点)+ 详读(全部) |
| Duke 不在线时 Agent 跑空 | 中 | 低 | digest 仍生成,落文件 · 看板可见 |
| 大量 lead 堆积(每日 50+ 条) | 低(初期) | 中 | 评分 < 50 自动 discarded · 看板只显示 ≥ 60 |
| M3 自动升级让 Duke 失控感 | 中 | 中 | 默认关闭,看板开关切换 · lifecycle 标 pending |
| digest 步骤 2 失败只剩 stats.json | 中 | 低 | 看板降级为"纯数据视图" · 显示 stats + 标"今日语义未生成" |

### 9.3 运营风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Skill 写的 mock 数据污染真实数据库 | 高(初期) | 中 | leads.jsonl 标记 `status=mock` · 入库时明显 |
| Duke 误操作关单/归档 | 中 | 中 | 关闭需填 reason · 归档 30 天后才生效 |
| Agent 摘要误导(无证据瞎说) | 中 | 中 | 摘要必填 evidence_refs · 看板标"🤖 参考" |
| 看板 UI 误改 bid 字段(无意) | 低 | 中 | 写操作必经命令面板 + reason 必填 |
| 数据丢失(无备份) | 低 | 高 | 每日自动备份 SQLite · 落 `~/.bidboard/backup/` |
| 摘要过程 Agent 无限重试 | 低 | 中 | Agent 跑有超时 · 失败 1 次不重试 · 看板提示 |

### 9.4 关键决策记录

| 决策 | 选择 | 原因 |
|------|------|------|
| 8 张表 vs 1 张表 | **1 张 bids + ltc_stage** | 改动最小,审计靠 command_execution |
| CLI vs Agent | **不做 CLI** | 价值低,Agent 调用命令注册更直接 |
| Token + Scope | **本地模式无 token** | 个人使用,信任本地 |
| 16 命令合并 | **11 命令** | 把 3 个 PATCH 合并为 update_field |
| 8 张表 LTC | **不拆** | 1 张表 + ltc_stage 字段表达 |
| 摘要位置 | **digests/YYYY-MM-DD.md** | Agent 写文件,不进 SQLite(不进事实) |
| 触发方式 | **cron + 手动 + Agent 三入口** | 覆盖主路径 + 临时 + 兜底 |
| 数据汇点 | **banner UI 是唯一数据展示** | Skill/Agent 都写文件,UI 拉取展示 |
| **v5.1:摘要触发** | **按需 + 实时推送** | 不再每日 11:00 cron,改"Duke 进看板时检测"+"新 lead 实时 toast" |
| **v5.1:M3 自动升级** | **P0 + 80+ 自动 lead.promote(待确认)** | 减少 Duke 重复操作,但保留确认权 |
| **v5.1:M4 简化** | **状态显示 + 立即跑** | 不做复杂对话框,推荐 cron,纯数据可按钮 |
| **v5.2:摘要协作** | **Agent(语义) + Skill(统计)** | 分工明确,纯数据不绕 Agent,语义必走 Agent |
| **v5.2:Skill 调用方式** | **看板直调 + Agent 调** | 纯数据走按钮直 subprocess;需语义走 Agent |
| **v5.2:摘要步骤拆分** | **2 步(stats.json + digest.md)** | 失败可降级 · 中间产物可复用 · 调试可观测 |

---

## 附录 A:变化日志

### v0.3.2(2026-08-14)·本版 / 产品发布版

- **产品版本号 v0.3.2 = PRD v5.2 终稿**(Duke 20:39 决定)
- **整合 v5 原文 + v5.1 4 修改 + v5.2 摘要协作增量**
- **本版为唯一 truth**,后续实施按本版走
- 关键新增:
  - 第 1.4 节 摘要协作原则(Skill 跑基础统计 / Agent 做语义归纳)
  - 第 3.4 节 M6 摘要协作流程(2 步骤:stats.json → digest.md)
  - 第 4.4 节 摘要协作架构说明
  - 第 5.1 节 场景 S1 实时推送 + 按需摘要
  - 第 5.1 节 场景 S3 M4 简化 + 场景 S6 M3 自动升级
  - 第 6.1-6.3 节 按需检测 + auto_promote
  - 第 7.1 节 实体 7 digest.md 升级模板(Agent+Skill 协作)
  - 第 7.1 节 实体 8 stats.json 中间产物
  - 第 7.3 节 路径 2/5 升级
  - 第 8.2 节 P0-MVP 5 天任务调整
  - 第 9.1-9.3 节 风险表补 v5.1/v5.2 相关项
  - 第 9.4 节 决策表补 v5.1/v5.2 决策记录
- **版本号对照**:产品对外 v0.3.2 / PRD 内部 v5.2 终稿 / 文件名 v0_3_2
- **文件重命名**:`prd-bid-board-v5_2-final-20260814.md` → `prd-bid-board-v0_3_2-final-20260814.md`
- **同步更新**:v5 review 加 v0.3.2 对照 / README 重写为 v0.3.2 / server.py 顶部加 v0.3.2

### v5.1 增量(2026-08-14)·已整合到本版

- **核心**:三维审查后 4 项 P1 修复
  1. **C1**:摘要触发 11:00 cron → 进看板按需 + 新 lead 实时推送
  2. **C2**:摘要每日生成 → 按需生成(Duke 进看板时检测)
  3. **C5**:M3 监听后,recommend=P0 且 score≥80 的 lead 自动调 lead.promote(D 仍需确认)
  4. **FP1**:M4 从"跑 Skill 复杂按钮"简化为"Skill 状态显示 + 立即跑按钮"
- **新生命周期**:lead.lifecycle 增加 `promoted_pending_confirm` 状态

### v5.2 增量(2026-08-14 18:03 Duke 意见)·已整合到本版

- **核心**:摘要协作模式明确
  - **摘要需要总结和归纳**——不是单纯堆数据,要做语义归纳
  - **Agent + Skill 协作**:
    - Skill 跑基础统计(数字、清单、分组、定时数据)
    - Agent 做语义归纳(优先级判断、要点提炼、趋势洞察)
    - 两者输出合并 → 写入看板
  - **Skill 脚本能力的两种调用方式**:
    1. 看板直接调用 Skill 脚本(subprocess,纯数据)
    2. Agent + Skill 协作(需语义归纳)
- **M6 重构为 2 步骤**:
  1. Skill 跑 digest_stats.py → digests/.tmp/stats.json
  2. Agent 读 stats.json + lead → digest.md + bid.attach_summary
- **失败可降级**:步骤 1 失败用昨日 digest;步骤 2 失败用 stats.json 纯数据视图

### v5(2026-08-14)·重新思考版

- **核心**:从 v4"借鉴 v0.3 数据中台"转向"个人 + Skill 主导"
- **删除**:CLI 工具(明确取消)
- **保留**:v3 看板/流程/管理 · v4 11 命令 + SQLite 持久化
- **新增**:M3 文件监听器 · M4 Skill 调用器 · M5 Agent Hook · M6 摘要生成器 · 商机 tab
- **架构**:Skill 独立抓取 → 写 `~/.bidboard/*.jsonl` → bid-board 监听拉取 → 看板展示
- **触发**:cron 自动(10:30) + 看板手动 + Agent 对话 三入口

### v4(2026-08-14)·借鉴 v0.3 版

- 11 命令注册 + 事务化 + 幂等 + 审计
- 借鉴 bid-news-kanban v0.3 架构
- 部分被 v5 调整(Skill 衔接方式改变)

### v3(2026-08-14)·基础版

- 5 阶段业务流 + 数据生命周期 + 手动+自动双通道
- 6 个外部脚本 · 日志收敛 · 时间维度总结 · 业务维度
- SQLite 持久化 + Lark 推送 + Mavis 语义 hook

---

## 附录 B:v5.2 实施 checklist(下次开干时)

> 本节是给"开干那天"的清单,不是设计约束。看完就扔。

**P0-MVP 5 天**:
- [ ] D1: 重构 lead_capture.sh(去掉 curl bid-board,只写文件)
- [ ] D1: 实现 M3 文件监听器(5s 轮询 → SQLite)
- [ ] D1: **M3 自动升级 P0 lead**(recommend=P0 + score≥80)
- [ ] D2: 看板新增"📥 商机" tab
- [ ] D2: **M4 简化为 Skill 状态显示 + ▶ 立即跑按钮**
- [ ] D3: **M6 步骤 1:digest_stats.py**
- [ ] D3: **M6 步骤 2:Agent 语义归纳模板**
- [ ] D3: **进看板按需检测 digest**
- [ ] D4: v3/v4 兼容测试(31/31)+ v5.2 新功能测试
- [ ] D5: Duke 真实跑一天

**P0-MVP 完成后验收**:
- [ ] 10:30 cron 跑通,leads.jsonl 有数据
- [ ] 10:35 实时推送 toast
- [ ] 11:00 进看板,30 秒内 digest 渲染
- [ ] 商机 tab 显示 lead + M3 自动升级待确认项
- [ ] M4 立即跑按钮,直调 Skill 成功
- [ ] 摘要分两屏(快读 + 详读)
- [ ] 31/31 质量测试 0 回归

---

> 本 PRD 由 prd-iterative 技能 + 三维审查 + v5.1/v5.2 增量整合生成
> 终稿:作为 v5.2 唯一 truth,后续实施按本版
