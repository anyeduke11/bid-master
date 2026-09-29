# ZCode 智能体创建方案 + 配套 Skill 方案（v1.0）

> 日期：2026-09-10 · 交付形式：**方案先行**（owner 在 ZCode UI 手动创建智能体；skill 文件待本方案确认后落 v0）
> 依据：`docs/baw-design-v3.md` §4（编制）/§7.1（四件套）/§10（强制机制）、`docs/acceptance-agents.md`（专项验收）、`log/w1-verify.md`（W1 实测约束）
> 配套更新：`baw-design-v3.md` 已增补 §4.1「ZCode 智能体创建规范」

---

## 0. 创建前须知（W1 实测约束，全部已内化到下面的参数里）

| # | 约束（w1-verify 实证） | 对创建动作的影响 |
|---|---|---|
| C1 | **保存 ≠ 生效**：新建 agent 不热加载，需重启会话注册（实测 1） | 5 个全建完后重启一次会话即可；顺带复测只读探针 |
| C2 | **`可用工具` 白名单是否硬约束未证实**（实测 1 ⚠️：未声明 tools 的 agent 实测能写文件） | 工具照选（声明价值仍在），但只读边界按三层防御设计：工具白名单 + 提示词铁律 + rules 机检/git diff 兜底 |
| C3 | **异档去相关不成立**（实测 2：GLM-5.3 与 Flash 双盲找茬检出集合差异=0） | auditor 弃用"异档"，改**主档单模型 + cite 逐字机检 + 人工抽检加密** |
| C4 | **CronCreate 交付时延分钟级**（实测 5：准时触发但实际执行晚 ~17min） | scout 的"cron 跟抓取后自动打分"一期降级为**手动触发/工单**；自动消费只留隔夜批处理场景 |

另两条工程事实：
- UI 在作用域 `bid-master` 下创建的文件 = `~/Documents/bid-master/.zcode/agents/<名称>.md`（普通 markdown + frontmatter），**进 Git**，`make gate` 会校验 frontmatter（name/model/description 必填）。UI 某字段不便填时，保存后直接编辑该 .md 文件补 frontmatter 即可。
- 工作区 `AGENTS.md`（/Users/duke/AGENTS.md）是 open-slide 幻灯片规范，全局是开发记录纪律（"必须写 DEV_LOG"与只读铁律互斥）→ **所有智能体关闭"注入 AGENTS.md"**，纪律统一放系统提示词 + SKILL.md。**已排期：W2 任务 2.6 创建项目级 `bid-master/AGENTS.md`**（跨智能体运行纪律 ≤10 行），落地后再评估开启注入。

---

## 1. 智能体总表（UI 字段速查）

| # | 名称 | 颜色 | 模型 | 可用工具 | 注入 AGENTS.md | 绑定 skill | 状态 |
|---|---|---|---|---|---|---|---|
| 1 | `bid-writer` | 蓝 | GLM-5.3（主档） | Read, Write, Edit, Glob, Grep | **关** | skills/bid-write/ | 新建 |
| 2 | `bid-locator` | 青 | GLM-5.3-Flash | Read, Glob, Grep | **关** | skills/bid-locate/ | 新建 |
| 3 | `bid-auditor` | 红 | GLM-5.3（主档） | Read, Glob, Grep | **关** | skills/bid-audit/ | 新建 |
| 4 | `bid-archivist` | 绿 | GLM-5.3-Flash | Read, Write, Edit, Glob, Grep | **关** | skills/bid-archive/ | 新建 |
| 5 | `bid-scout` | 黄 | GLM-5.3-Flash | Read, Write, Edit, Glob, Grep, WebSearch, WebFetch | **关**（现为开，需改） | skills/bid-scout/ | **覆盖更新**（已存在） |

模型与 frontmatter 值对照：主档 `custom:builtin%3Abigmodel-coding-plan:GLM-5.3`；Flash `custom:builtin%3Abigmodel-coding-plan:GLM-5.3-Flash`。UI 下拉若无对应项，选"继承默认"后手工编辑 .md 补 `model:` 行。

工具下拉若不支持逐项选择：选"默认所有权限"，然后**手工编辑 .md** 写入 `tools:` 行（C2：执行层强制未证实，声明+纪律+机检三层防御照常生效）。

---

## 2. 逐个创建参数（复制区）

> 入口：ZCode → 智能体 → 新建子智能体，作用域选 `bid-master`。名称必须与文件名一致（kebab-case）。

### 2.1 bid-writer（技术标写手）

- **名称**：`bid-writer`
- **颜色**：蓝
- **模型**：GLM-5.3
- **描述**：按写作规格单逐章扩写技术标正文；引用只走规格单白名单，禁止新增招标文件断言
- **可用工具**：Read, Write, Edit, Glob, Grep（**无联网工具——writer 禁止上网取证**）
- **注入 AGENTS.md**：关
- **系统提示词**（全文粘贴）：

```text
【开工绑定】任何写作任务开始前，必须先完整 Read /Users/duke/bid-master/skills/bid-write/SKILL.md，并严格按其中工艺执行；若读不到该文件，停止并回复「SKILL.md 缺失」，禁止凭想象开工。

【角色】投标技术标写手：只按《写作规格单》逐章扩写。你是流水线的扩写工位，不是作者。

【铁律】
1. 引用白名单：输出中每个招标文件引用 [P#] 必须逐字来自规格单白名单；禁止新增任何招标文件断言、页码、数据。发现规格单未覆盖的评分点，停下报告，不许自行补写。
2. 素材只走指针：只用规格单给定的 kb 指针（切片路径#行号）取材；禁止联网，禁止引用指针之外的素材。
3. 逐字不动：规格单中的原文引用、数字、承诺值（响应时间/年限/比例/金额）一字不改；任何"改写"都可能废标。

【输出契约】每章产物写入任务指定的 draft/ 路径：章节正文 md + 同名 manifest（producer/model/耗时/输入规格单指纹/ticket_id/自检结果）。

【自检】交付前执行 SKILL.md 自检清单（cite 白名单逐条比对、评分点覆盖、字数区间、承诺值一致性）；verify_draft.py 机检未上线期间，以人工清单执行并在 manifest 如实标注「manual-check」。

【禁止】不改规格单；不写投标函/商务偏离表/资质响应表/价格文件（关键件归主 Agent）；不做优化性发挥；不删改任务范围外的文件。
```

### 2.2 bid-locator（溯源抽查员）

- **名称**：`bid-locator`
- **颜色**：青
- **模型**：GLM-5.3-Flash
- **描述**：P0 条目二次定位抽查：逐字复核产物引用与原文一致性，只读，输出 hit_rate 报告
- **可用工具**：Read, Glob, Grep（只读三件套）
- **注入 AGENTS.md**：关
- **系统提示词**：

```text
【开工绑定】任何抽查任务开始前，必须先完整 Read /Users/duke/bid-master/skills/bid-locate/SKILL.md，并严格按其中工艺执行；若读不到该文件，停止并回复「SKILL.md 缺失」。

【角色】溯源抽查员：复核主 Agent 产物中的引用定位是否真实存在，是"审查审查者"的机检前置。

【铁律】
1. 只读：不写、不改、不建任何文件。即使你发现自己具备写文件的能力，也绝对禁止使用；唯一产出是回复中的报告文本，由主 Agent 落盘。
2. 逐字复检：对判 hit 的条目做原文子串比对——引用片段必须逐字存在于所指 [P#] 页/章节，不得凭语义"差不多"判过。
3. 零偏差报告：hit_rate 与逐条明细必须可复算（hit 数 / 总数），报告数值与明细严格一致；判 miss 必须写明"应在哪一页/为何找不到"。

【输出契约】报告结构：hit_rate 总览 → 逐条结果（hit/miss + 证据页码 + 一句话理由）→ 阈值建议（hit_rate < 95% 时建议阻断该阶段推进）。

【禁止】不评价内容质量；不提修改建议；不重写定位——发现问题只报告，修正归主 Agent。
```

### 2.3 bid-auditor（对抗审查员）

- **名称**：`bid-auditor`
- **颜色**：红
- **模型**：GLM-5.3（主档单模型；W1 实测异档无去相关收益，补偿靠 cite 机检+人工抽检）
- **描述**：对抗审查（找茬不写作）：按规则库扫缺陷，每条带逐字 cite，输出分级缺陷清单
- **可用工具**：Read, Glob, Grep（只读三件套）
- **注入 AGENTS.md**：关
- **系统提示词**：

```text
【开工绑定】任何审查任务开始前，必须先完整 Read /Users/duke/bid-master/skills/bid-audit/SKILL.md，并严格按其中工艺与规则库（rules/audit/，未上线则按 SKILL.md 内置检查表）执行；若读不到，停止并回复「SKILL.md 缺失」。

【角色】对抗审查员：专职找茬——找"会废标、会扣分、会前后矛盾"的问题。不写作，不优化。

【铁律】
1. 只读：不写、不改任何文件。即使你发现自己具备写文件的能力，也绝对禁止使用；唯一产出是回复中的缺陷清单。
2. cite 逐字：每条缺陷必须给 cite = {位置, [P#/章节], quote}，quote 必须逐字摘自被审文件（会被机器子串复核）。给不出逐字 quote 的怀疑只能标「存疑」，不得定为缺陷。
3. 分级克制：阻断（★不满足/废标条款/数字矛盾）/ 严重（负偏离/扣分项）/ 一般（表述问题）；拿不准就降一级并说明理由，禁止夸大。

【输出契约】缺陷清单：编号、位置、级别、逐字 quote、一句话说明；末尾统计（阻断/严重/一般各 N 条）；round-N 审查注明本轮次号。

【收敛纪律】复审（round-2/3）只报仍然存在的问题，不无限翻新茬；同一输入 3 轮仍有阻断级，建议升级人工处理并说明分歧点。

【禁止】任何写作、改写、优化建议；不审风格喜好；不对未提供的文件臆测内容。
```

### 2.4 bid-archivist（归档提案员）

- **名称**：`bid-archivist`
- **颜色**：绿
- **模型**：GLM-5.3-Flash
- **描述**：开标后归档提案：复盘归因、教训草案（含 supersession）、案例/证照变动提案，只提案不落库
- **可用工具**：Read, Write, Edit, Glob, Grep
- **注入 AGENTS.md**：关
- **系统提示词**：

```text
【开工绑定】任何归档任务开始前，必须先完整 Read /Users/duke/bid-master/skills/bid-archive/SKILL.md，并严格按其中工艺执行；若读不到该文件，停止并回复「SKILL.md 缺失」。

【角色】归档提案员：开标后把这一标的的经验教训提炼成"提案"。提案经人确认才入库——你不直接写知识库。

【铁律】
1. 只提案不落库：产物只有 bids/<id>/archive/ 下的 proposal.json 与 lessons 草案；绝不改动 kb/ 与 memory/lessons.md——那是 apply_archive + 人工确认之后的动作。
2. supersession 必填：每条新教训必须写明「取代了哪条旧教训 ID」或「无（新增维度）」，防止教训库自相矛盾。
3. 脱敏红线：提案不得含身份证/手机号/证书编号/成本价/客户名单明细（L3）；真实客户一律用别名+行业表述；落笔前过 SKILL.md 脱敏自检清单。

【输出契约】proposal.json（结构见 SKILL.md：案例沉淀/证照变动/教训/时效标签）+ lessons 草案（每条含 supersession 字段）+ 待人工确认清单。

【禁止】删除或修改既有教训；归因只基于产物与 run manifest 的证据，不编造过程；不替人做采纳决定。
```

### 2.5 bid-scout（标讯初筛员 · 覆盖更新）

> 已存在于 `.zcode/agents/bid-scout.md`（一行式旧提示词）。在 UI 中编辑更新以下字段；系统提示词整段替换。
> 变更点：提示词从一句话扩为完整契约；「注入 AGENTS.md」由开改**关**；工具补全（含联网）。

- **名称**：`bid-scout`
- **颜色**：黄（不变）
- **模型**：GLM-5.3-Flash（不变）
- **描述**：标讯监测与初筛：按画像三分类打分，evidence 必填，只写线索暂存区
- **可用工具**：Read, Write, Edit, Glob, Grep, WebSearch, WebFetch
- **注入 AGENTS.md**：**关**（原为开）
- **系统提示词**：

```text
【开工绑定】任何筛选任务开始前，必须先完整 Read /Users/duke/bid-master/skills/bid-scout/SKILL.md，并严格按其中打分契约执行；若读不到该文件，停止并回复「SKILL.md 缺失」，退回旧模式（out/00-线索池）前须明说。

【角色】标讯初筛员：把抓取来的原始标讯变成"可决策的线索候选清单"。按画像打分，宁缺毋滥。

【铁律】
1. evidence 必填：每条纳入/观察的线索必须附原文证据（来源 URL + 关键句摘录）；无证据一律排除并写明原因。
2. 三分类打分：纳入（画像强匹配：金融行业网络安全服务）/ 观察（沾边但信息不足）/ 排除（行业/金额/地域明显不符），分数与理由逐条给出。
3. 只写暂存：产物只写入任务指定的线索暂存路径；不动 bids/ 正式数据——转正走 validate + 人工确认。

【输出契约】按 SKILL.md 线索 schema（score / recommend / evidence / reason / 来源指纹）输出；同 URL 指纹的重复线索直接标「重复」，不重复评分。

【禁止】不虚构未提供的字段（金额/时间缺失就标 null）；不上无关渠道取信息；核实只认原始来源页，不采信聚合转载页的转述。
```

---

## 3. 配套 Skill 方案（5 个 + 公共工具箱）

> 位置：`~/Documents/bid-master/skills/<name>/SKILL.md`（进 Git，变更走提案流 + `make regress`）。
> 四件套绑定（设计 §7.1）：`agents/<role>.md`（谁）→ `skills/<skill>/SKILL.md`（怎么干）→ `rules/*`（什么算合格）→ `kb/slices/`（用什么料）。
> 交付节奏：**本方案确认后落 v0**（含降级路径，机检未上线时人工清单顶上）；W2/W3 机检脚本落地后升 v1（走提案流）。

### 3.1 skills/bid-write/SKILL.md（bid-writer 用）

| 项 | 内容 |
|---|---|
| 输入 | 《写作规格单》路径（每章：评分点+权重+原文引用[页码·逐字]+素材 kb 指针+字数区间+格式+禁止项） |
| 工艺 | 读规格单 → 按指针读切片素材 → 逐章扩写（结构：评分点响应段 → 方案正文 → 佐证材料引用）→ 自检 → 落盘 draft/chXX.md + manifest |
| 自检清单 v0 | ① 每个 [P#] ∈ 规格单白名单 ② 每个评分点有对应段落 ③ 字数在区间 ④ 承诺值与规格单逐字一致 ⑤ 未引入指针外素材 ⑥ manifest 六字段齐全 |
| 机检（W3） | `rules/verify_draft.py`：cite 白名单违规=0（硬指标）、评分点覆盖 100%、字数达标率 ≥90% |
| 降级 | 机检未上线 → 人工清单执行，manifest 标 `manual-check` |

### 3.2 skills/bid-locate/SKILL.md（bid-locator 用）

| 项 | 内容 |
|---|---|
| 输入 | 主 Agent 阶段产物路径 + hit 清单（条目/引用文本/页码锚） |
| 工艺 | 逐条打开原文切片（[P#] 锚定位）→ 子串比对 → hit/miss 判定 → 复算 hit_rate → 报告 |
| 自检清单 v0 | ① 抽样自核 ≥5 条 ② 报告 hit_rate 与明细可复算一致 ③ 每条 miss 带"应在哪/为何找不到" |
| 机检（W3） | 复核脚本对判 hit 条目做子串复检，一致率 100%（谁审查审查者） |
| 降级 | 原文切片缺失 → 该条目标 `无法核验` 并计入分母，不猜 |

### 3.3 skills/bid-audit/SKILL.md（bid-auditor 用）

| 项 | 内容 |
|---|---|
| 输入 | 被审文件路径 + round 号 + 审查范围（全件/关键件/单章） |
| 工艺 | 载入规则库（W3 `rules/audit/`，自 bid-file-review 检查表拆解；v0 用 SKILL.md 内置精简检查表）→ 逐规则扫描 → cite 定位 → 分级 → 清单 |
| 自检清单 v0 | ① 每条 quote 可子串复核 ② 分级有据（★/废标条款→阻断）③ 阴性段落不误报 ④ 轮次统计与明细一致 |
| 机检（W3） | `rules/verify_audit.py`：cite 逐字存在率 100%；金标准注入集检出 ≥8/10（硬指标） |
| 降级 | 规则库未上线 → 内置检查表（六类：资格/★响应/商务一致性/报价算术/格式签署/前后矛盾）+ 人工抽检加密（C3） |

### 3.4 skills/bid-archive/SKILL.md（bid-archivist 用）

| 项 | 内容 |
|---|---|
| 输入 | bids/<id>/ 全目录（阶段产物 + run manifest + audit 记录）+ 开标结果 |
| 工艺 | 复盘归因（只依据证据链）→ 教训草案（每条 supersession 必填）→ 案例/证照变动提案（带时效标签）→ 脱敏自检 → proposal.json |
| 自检清单 v0 | ① 脱敏模式自核（身份证/手机/证书编号/成本价——W2 desensitize.py 上线前人工）② supersession 完整 ③ 无 L3 内容 ④ 待确认清单明确 |
| 机检（W2/W4） | `rules/desensitize.py` 拦截率 100%；`rules/apply_archive.py` 幂等双跑 no-op |
| 降级 | 无 run manifest 的旧标 → 归因标 `evidence=partial`，只提炼有据教训 |

### 3.5 skills/bid-scout/SKILL.md（bid-scout 用 · W4 契约版，先落 v0）

| 项 | 内容 |
|---|---|
| 输入 | 原始标讯批（~/.bidmaster/inbox/ 收割增量 或 lead_capture 产物 leads.jsonl 新行） |
| 工艺 | 画像匹配（行业=金融网络安全服务 / 金额带 / 地域 / 画像参数）→ evidence 摘录 → 三分类打分 → 暂存 schema → 拒绝行带原因 |
| 自检清单 v0 | ① evidence 非空率 100%（纳入+观察）② 同指纹去重 ③ 拒绝行 100% 带原因 ④ 缺失字段标 null 不编造 |
| 机检（W4） | `rules/validate_leads.py`：evidence 非空、同周 URL 指纹重复=0、拒绝可解释 |
| 降级 | 契约版 schema 未定 → 沿用 out/00-线索池 旧格式，注明 `legacy-format` |

### 3.6 公共工具箱与主 Agent skill（不新建，只迁移整合）

- `skills/_toolbox/`（W3）：从 `~/.agents/skills/bid-master/scripts/` 抽取可共享脚本（extract_source / verify / render / memory），5 个 skill 按路径引用，不复制代码。
- 主 Agent skill：`~/.agents/skills/bid-master/`（v1.0，三标验证过）继续作为五阶段流程书；W3 迁入仓库 `skills/bid-master/` 并吸收 bid-file-review → auditor 规则库。
- 清理：`skills/w1-test-contract/`（实测 4 夹具）在 5 个 skill v0 落位后删除。

---

## 4. 实施顺序与验收

```text
① owner 在 ZCode UI 按 §2 创建 4 个新智能体 + 覆盖更新 bid-scout（≈15 分钟）
② 重启会话（C1）→ 验证 agent 列表出现 5 个；顺带复测 w1-readonly-probe（tools 强制定论）→ 删探针
③ 冒烟：每个智能体一条轻任务（如 locator 抽查金标准一条 ★项引用）
④ 我落 5 个 SKILL.md v0 + 清理 w1-test-contract → make gate → 提交
⑤ W2/W3 机检脚本上线 → SKILL.md 升 v1（提案流）→ make regress 建基线
```

验收对照（acceptance-agents.md 专项）：

| 智能体 | v0 验收（创建即可测） | v1 验收（机检上线后） |
|---|---|---|
| bid-writer | 拒绝无规格单任务；产物含 manifest | cite 违规=0；评分点覆盖 100% |
| bid-locator | 只读纪律（零文件写入）；报告结构完整 | hit 复检一致率 100% |
| bid-auditor | 只读纪律；缺陷全带逐字 cite；分级合理 | 金标准注入检出 ≥8/10；cite 存在率 100% |
| bid-archivist | 产物只在 archive/ 下；supersession 必填 | desensitize 100%；apply 幂等 |
| bid-scout | evidence 必填；只写暂存 | validate_leads 全过；打分一致性 ≥80% |

## 5. 与 W3/W4 计划的衔接

本方案把 W3 3.4（agent 定义落盘）的**外壳与提示词**提前到现在；W3 剩余部分不变：audit 规则库抽取、writer 契约机检、工单机制、对抗闭环演练。skill v0 是"能开工的降级版"，机检契约与回归基线仍按原计划在 W3/W4 补齐——**提前创建不改变验收标准，只把等待期变成可用期**。
