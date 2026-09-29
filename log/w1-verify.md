# W1 实测记录 · 6 项（2026-09-10 执行）

> plan-baw-implementation.md §5 / baw-design-v3.md §13。执行环境：ZCode 桌面版（app 3.11.2），主档 GLM-5.3，项目级 bid-scout pin GLM-5.3-Flash。
> 判定口径：✅ 通过标准成立 / ❌ 不成立已启用 fallback / ⚠️ 部分成立或有条件成立。**失败与存疑如实记录**。

---

## 实测 1 · agent frontmatter `tools:` 只读强制

> **2026-09-10 晚间复测定论（`log/agent-smoke.md` #1）：✅ 通过**——owner UI 创建 5 个智能体后，w1-readonly-probe 完成注册并可调用；写文件任务实报 `NO_WRITE_TOOL`，自列工具=Read/Glob/Grep/RespondToCoordinator，无任何写能力。**frontmatter `tools:` 白名单是硬约束**，locator/auditor 的只读第一层防御成立。
> 注册结论修正：UI 创建即时注册；.md 文件直写为延迟注册（当时未注册，晚间已可调）。

- **方法**：新建 `.zcode/agents/w1-readonly-probe.md`（`tools: Read, Glob, Grep`，Flash 档），尝试以 `subagent_type=w1-readonly-probe` 派发"写 /tmp 文件"任务；另派 bid-scout（未声明 tools，对照组）执行同类写任务。
- **结果**：
  - 探针派发失败：`Agent type 'w1-readonly-probe' not found`（可用列表仅含会话启动时已注册的 agent）→ **项目级 agent 定义不在会话中途热加载，需重启会话注册**。
  - 对照组 bid-scout：`WRITE_SUCCEEDED /tmp/w1-scout-probe/scout.txt`（Write 工具真实可用）→ **未声明 tools 的 agent 具备全量工具含写**。
- **判定（当日原始记录）**：⚠️ 部分验证。`tools:` 白名单是否被强制执行，须重启会话后用探针复测（探针文件已就位，测后可删）。
- **设计含义**：locator/auditor 的"只读"不能只靠 agent 定义（本轮未证）；**fallback（git diff 防护目录 + rules 机检兜底）为有效防线**，与设计 §12.2 第 4 条一致。

## 实测 2 · 异档模型去相关（GLM-5.3 vs GLM-5.3-Flash）

- **方法**：`tests/golden/w1-defect-sample.md`（虚构标书节选，10 处已知缺陷，答案键 `w1-defect-sample.key.json` 不进 prompt）。bid-scout（Flash）与 general-purpose（主档）同 prompt 双盲找茬，比对对答案键的检出集合。
- **结果**：
  - Flash 档：输出 10 条，命中答案键 **9/10**（缺 D1 公司名"安信某网络安全服务商"≠"某网络安全服务商某网络安全服务商"，需外部工商知识），1 条一般级误报（保证金到账凭证，key 判为正确响应）。
  - 主档：输出 11 条，命中 **9/10**（同样缺 D1；业绩窗口拆成 2 条计 1 项），同类 1 条一般级误报。
  - **检出集合对称差 = 0 条**。
- **判定**：❌ 按通过标准（差异 ≥2 条）**不成立** → 启用 fallback：**接受部分去相关，人工抽检加密**。
- **设计含义**：同家族（GLM）两档模型在投标缺陷这类任务上行为高度一致——"异档去相关"对同一家族不成立。auditor 的补偿结构回归设计 §14 三重补偿（机检 cite 逐字 + 人工抽检 + golden 注入集）；W3 若引入真正异构模型（非 GLM 家族）可重测本样本。

## 实测 3 · run_in_background 并行汇合

- **方法**：同一条消息并行派发 2 个后台任务（Flash 审计 + 主档审计），随后再叠加第 3 个后台任务（bid-scout 写探针对照组）。
- **结果**：3 个任务全部启动成功、全部完成、结果完整可收集、内容互不串扰、无时序竞争。
- **判定**：✅ 通过（writer 分章并行 / locator∥auditor 的前提成立）。

## 实测 4 · 子智能体"开工先 Read SKILL.md"

- **方法**：`skills/w1-test-contract/SKILL.md` 内置仅读文件可知的校验短语与强制 JSON 输出契约；派 general-purpose，prompt 第一条为"开工前必须先 Read 该 SKILL.md"。
- **结果**：输出为严格契约 JSON：`contract_version: w1-test-contract/1`、`checksum_phrase: 琥珀-七号-回声`（逐字一致）、`read_skill_first: true`。
- **判定**：✅ 通过——"开工先 Read SKILL.md"绑定有效，输出含契约结构（设计 §7.2 效果验证路线成立，无需观测读取行为）。

## 实测 5 · CronCreate 定时消费 queue/

- **方法**：真实工单 `~/.bidmaster/queue/W1T5-20260910-143649.json`（status=generated）；CronCreate 一次性任务（预定 14:39:52，delay 3 分钟），指令为读取工单→追加消费日志→改工单 status=executed。
- **结果**：
  - 调度层 ✅：`lastRunAt` = 预定时刻 +7 秒（14:40:19），`runCount=1`，`lifecycleStatus=completed`——准时触发、生命周期闭环。
  - 执行层（首次触发）：❌ 未落任何产物——14:52 复查时消费日志不存在、工单 status 仍为 generated（全盘搜索无 w1-cron-consume.md）。
  - 执行层（补记 14:56）：工单提示词**实际交付执行成功**（14:56:38，比预定晚约 17 分钟）：消费日志已写、工单 status→executed（executed_by=cron）。判定口径因此修正：链路"可用但**不及时**"，且首次触发与实际执行之间存在无产物窗口，交付时延不可控。
- **判定**：⚠️ 半通过（调度 ✅ / 执行 ✅ 但延迟 ~17 分钟、时延不可控）→ 一期按设计走 fallback：**纯人工复制启动**（本就是 D13 一期方案：人=审批位，机制不受损）。
- **设计含义**：二期若要 CronCreate 自动消费 queue/：①工单格式无需改动（本次按工单指令完整执行）；②须接受/解决分钟级以上的交付时延（不适合有 deadline 的当日必办类工单，适合隔夜批处理类）；③定时会话的文件写权限需专项确认（首次触发零产物的原因仍未知，无法排除权限因素）。

## 实测 6 · ZCode CLI 带 prompt 启动

- **方法**：PATH / npm 全局 / `/Applications/ZCode.app/Contents/MacOS/` / `~/.zcode/cli/` 多路探测可独立调用的 CLI；`strings` 探测 `zcode://` 深链子路径。
- **结果**：本机为 ZCode.app 桌面版（3.11.2），**无独立 CLI 可执行文件**；`zcode://` 深链已注册但未发现带 prompt 启动会话的公开语义（进程名 `zcode-cli` 为应用内部子进程）。
- **判定**：❌ 不成立 → fallback **纯复制粘贴启动**（机制不受损）；"看板拉起 ZCode"维持一期不可行判定（与设计 §13 一致）。

---

## 汇总与 W2 前置动作

| # | 实测项 | 判定 | fallback/待办 |
|---|---|---|---|
| 1 | tools 只读强制 | ✅（晚间复测定论） | 硬约束成立；探针已删除 |
| 2 | 异档去相关 | ❌→fallback | 人工抽检加密；同家族不成立，异构模型可重测 |
| 3 | 后台并行汇合 | ✅ | — |
| 4 | Read SKILL.md 契约 | ✅ | — |
| 5 | CronCreate 消费 | ⚠️ 半通过 | 一期人工复制；自动消费需接受分钟级+交付时延（实测 ~17min） |
| 6 | CLI 带 prompt | ❌→fallback | 纯复制粘贴 |

**W2 前置**：① 重启会话复测实测 1（约 2 分钟）；② 定时会话权限问题挂入 W2 watcher/工单设计考量；③ 本记录随金标准草稿一并进 Git（commit 见 DEV_LOG）。
