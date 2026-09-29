# 独立智能体验收标准（BAW v3.0）

> 适用：主 Agent（bid-master 主链路）+ 5 个子智能体（scout/writer/locator/auditor/archivist）
> 原则：验收只认**可机检或可抽检复算**的证据；自我报告不作为验收依据（信任零假设）

---

## 1. 通用验收（全部智能体适用）

| # | 项 | 标准 | 采集方式 |
|---|---|---|---|
| G1 | 契约符合率 | 连续 ≥50 次运行产物 schema 通过率 ≥98% | run manifest 统计脚本 |
| G2 | 溯源完整 | run manifest 必含 producer/模型/时长/输入指纹/ticket_id/校验结果，缺失=该次运行不计入统计 | 同上 |
| G3 | 降级可用 | 断掉该 agent 后兜底路径演练 1 次成功（脚本/人工 15 分钟内顶上） | 演练记录 |
| G4 | 回归保护 | 该 agent 定义/skill 任一变更后 `make regress` 无指标退化 | 回归对比表 |
| G5 | 成本在档 | 单次运行 token/时长有记录，月度合计在预算内 | run manifest |

**Harness 五标志对照**：产出可机检（G1）、引用可回溯（各专项）、变更可回归（G4）、失败可降级（G3）、教训可回流（archivist 专项）。

## 2. 金标准测试集（`tests/golden/`）

- 素材：金标准演练标（唯一有完整投标文件，阶段 0–3 全可对照）——**指某证券通信机构·安全技术支持服务采购（CGXM-IT-SJ-2026-030，bid_id `2026-GOLD-jishu`，lingxi-claw/20260623 批次）；注意 ≠ 某证券交易所·重保协防标（048，20260618 批次，无投标文件）**。指针与 sha256 指纹档案：`tests/golden/goldstd/materials.json`
- 标注：全部★项、全部评分点、已知缺陷注入集（10 个，供 auditor 检出率测试）。当前状态：★项 18 条 + 评分点为 **draft（lingxi-claw 结构化提取），待人工对照原始 PDF 确认后方可作为召回基线**（txt 转换丢表格，P1 风险）；确认前不得宣称 100% 召回
- 用途：①新 agent 上线验收 ②任何 prompt/skill/agent 定义/模型变更后的回归基线
- 命令：`make regress` 输出召回率/检出率/耗时/token 与上次对比

## 3. 各智能体专项验收

### 3.1 主 Agent（bid-master 五阶段主链路）

| 项 | 标准 | 验证 |
|---|---|---|
| ★项召回率 | **100%（硬指标）** | 对照金标准 |
| hits 关键词对账 | 100%（收录+排除逐条理由覆盖全部命中） | scan_keywords 台账 |
| 定位准确率 | ≥95%（[P#·章节]「逐字摘录」抽样 20 条） | 人工/locator 复核 |
| lessons_applied | 阶段 0 产物含字段且引用有效教训 ID | S2→S3 门禁 |
| 单上下文铁律 | 全程无子智能体参与语义解析 | 运行协议+日志审查 |

### 3.2 bid-scout（标讯初筛）

| 项 | 标准 | 验证 |
|---|---|---|
| evidence 非空率 | 100% | validate_leads 机检 |
| 去重率 | 同周重复线索（同 URL 指纹）=0 | validate_leads |
| 打分一致性 | 抽 20 条，与人工判断一致（纳入/观察/排除三分类）≥80% | 人工抽检 |
| 拒绝可解释 | validate 拒绝行 100% 带原因且入 rejects | 脚本统计 |
| 降级演练 | 停 scout，lead_capture 裸抓+人工筛可用 | G3 |

### 3.3 bid-writer（章节扩写）

| 项 | 标准 | 验证 |
|---|---|---|
| **cite 白名单违规** | **=0（硬指标，任何 [P#] 引用不在规格单白名单=幻觉断言）** | verify_draft 机检 |
| 评分点覆盖率 | 规格单每个评分点在产出中有对应段落，100% | verify_draft 机检 |
| 字数区间达标率 | ≥90% 章节 | verify_draft |
| 素材指针消费 | 仅使用规格单给定 kb 指针，未引入外部断言 | verify_draft + 人工抽检 |
| 人工盲评 | 抽 3 章，"不返工可直接进审计"≥2/3 | 人工评审 |
| 降级演练 | 停 writer，人按规格单写可用 | G3 |

### 3.4 bid-locator（溯源抽查）

| 项 | 标准 | 验证 |
|---|---|---|
| hit 复检一致率 | 脚本对判 hit 的条目做子串复检，100% 一致（谁审查审查者） | 复核脚本 |
| 报告零偏差 | 报告 hit_rate 与脚本复算值差=0 | 脚本复算 |
| miss 判定正确性 | 抽检判 miss 条目 ≥90% 属实 | 人工 |
| 阈值联动 | hit_rate < 阈值时正确阻断阶段推进 | S4→S5/S5→S6 门禁演练 |

### 3.5 bid-auditor（对抗审查）

| 项 | 标准 | 验证 |
|---|---|---|
| **金标准注入检出率** | **10 个已知缺陷检出 ≥8（硬指标）** | tests/golden 注入集 |
| 误报率 | 正常段落误判为严重/阻断 ≤1 | 金标准阴性样本 |
| cite 逐字存在率 | 每条缺陷 cite.quote 逐字存在于原文对应页，100%（审计员引用也逃不过机器复核） | 机检脚本 |
| 判级稳定性 | 同输入两轮独立运行，阻断级判定一致 ≥90% | 双跑对比 |
| 角色纪律 | 输出仅缺陷清单，无写作/优化内容（prompt 越权检查） | 人工抽检 |
| 循环收敛 | round-1→修复→round-2 阻断数单调下降；3 轮不过升级人工（不无限自旋） | 演练记录 |

> **W1 实测 + owner 定版（2026-09-10）**：同家族（GLM）双档去相关不成立——10 缺陷双盲找茬检出集合差异=0（`log/w1-verify.md` 实测 2）。owner 定版 auditor 用 **Flash**（高频低成本档）；注入集正式验收两跑 8/10、7/10——**Flash 单跑未稳定 ≥8，故本指标定版为"LLM 检出 + verify_audit 机检补位"组合判定**：LLM 缺陷清单 + `rules/verify_audit.py` 机检（cite 逐字 / requirement 一致性，已实证机械抓到 LLM 漏项）合并计分；若日后接入非 GLM 家族模型，可用 `tests/golden/w1-defect-sample` 及注入集重测纯 LLM 口径（答案键已留）。

### 3.6 bid-archivist（归档提案）

| 项 | 标准 | 验证 |
|---|---|---|
| apply_archive 幂等 | 同 proposal 重复应用=no-op | 双跑对比 |
| supersession 正确 | 新教训显式标注取代的旧教训 ID，且旧条目标"沉淀" | lessons.md 检查 |
| 脱敏 | 提案内容过 desensitate 100% | 机检 |
| 人工采纳位 | lessons 采纳需人确认（L2→L3），确认前不入库 | 流程演练 |
| 飞轮闭环 | 归档后下一标阶段 0 lessons_applied 能引用到新教训 | 端到端演练 |

## 4. 回归纪律（软件工程化承诺）

1. 改任何 agent .md / SKILL.md / rules / 工单模板 → 必跑 `make regress` 并保留对比表
2. 变更走提案流（.pending → validator → 人确认 → git commit），禁止热改生效中的定义
3. 每次 regression 结果与 run manifest 归档 `runs/`，作为体验报告 Q3（过程复盘）与 Q5（对比）的一手素材
4. 失败轮次与定位错误**如实记录**——报告最有说服力的恰是这些

## 5. 验收命令速查

```bash
make gate            # 全量门禁（=set-stage 同套校验）
make regress         # 金标准回归：召回/检出/耗时/token 对比
make rebuild-cache   # 看板投影缓存重建（证明看板不拥有状态）
python3 rules/validate_leads.py --week current     # scout 产物统计
python3 rules/verify_draft.py --bid <id> --all     # writer 机检
python3 rules/verify_audit.py --bid <id> --round N # auditor cite 复核
python3 rules/apply_archive.py --bid <id> --dry-run # archivist 幂等预演
```
