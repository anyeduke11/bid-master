# tests/golden/ — 金标准与回归基线

> acceptance-agents.md §2：新 agent 上线验收 + 任何 prompt/skill/agent 定义/模型变更后的回归基线。
> 命令：`make regress`（W4 落地 regress.py；当前 exit 2 提示未落地）。
> **评测方法（owner 定版 2026-09-10）：金标准评测以 `bid-file-review` v2.5 技能为基准**——
> 其阶段零核对单体系（G 资格 / V 废标 / S 评分 / F 格式 / D 文件清单 / TR 技术需求 / SCS 服务标准 + ★▲专项 + 业绩4条件 + 社保窗口）
> 即金标准标注与召回率的对照口径；szt 素材中的 `audit_checklist.md` / `audit_data.json` 本就是 bid-file-review 的结构化产物，
> 金标准 ★项/评分点草稿由其派生（血缘：lingxi-claw 批次 → audit_data.json → star-items/scoring-points draft）。
> `rules/audit/`（W3 3.1）即 bid-file-review 检查表的机检拆解，落地后 `make regress` 以规则库自动评测。
>
> **公开库说明（2026-09-29）**：`goldstd/` 目录含客户招标文档的结构化指针与引文，属本地保留件——已入 `.gitignore`，**不随公开仓库分发**；公开库上 `make regress` 的指纹核对段自动跳过（`rules/regress.py` 已兼容缺件）。

## 内容

| 文件/目录 | 内容 | 状态 |
|---|---|---|
| `goldstd/materials.json` | **金标准演练标**（CGXM-IT-SJ-2026-030 安全技术支持服务采购，bid_id `2026-GOLD-jishu`，三标中唯一有完整投标文件）素材**指针 + sha256 指纹** ×9：招标全文、投标文件全文+四分册、审计核对单、评审报告、结构化审计数据。原件留在 `~/Documents/lingxi-claw/20260623-15-53-04-363/` 不复制（L2，不进 Git） | W1 ✅ |
| `goldstd/star-items.draft.json` | ★项草稿 **18 条**（lingxi-claw 已按页码锚结构化提取），逐条待人工对照原始 PDF 确认 | **draft，待人工确认** |
| `goldstd/scoring-points.draft.json` | 评分点草稿：价格 30 分（价低者优公式）+ 商务 4 项 + 技术 5 项 + score_summary + 资格项 | **draft，待人工确认** |
| `w1-defect-sample.md` + `w1-defect-sample.key.json` | 10 缺陷注入样本（虚构文本，与金标准演练标无关）+ 答案键——W1 实测项 2 用；W3 起按此模式对某证券通信机构真实产物扩充为 auditor 正式注入集（检出 ≥8/10 硬指标） | W1 ✅ |
| `regress.py`（W4） | 回归执行器：召回率/检出率/耗时/token 与上次对比 | W4 |
| `baseline-*.json` → `runs/` | 回归基线（进 Git 的仅 `runs/baseline-*.json`） | W4 |

## 标注协议（人工部分）

1. **★项确认（升级 v1 的门槛）**：对照**原始招标 PDF** 逐条确认 `star-items.draft.json`（改 `status: draft → confirmed`，可增删改）。txt 全文有 [P#] 页锚但**表格在转换中丢失**（plan 风险 P1 实证），涉及评分附表/前附表的条目务必对 PDF 复核。
2. **评分点确认**：`scoring-points.draft.json` 逐项核对分值边界与档位描述（优秀/良好/一般），确认后同样改 `status`。
3. 两文件全部 confirmed 即"金标准 v1"交付；此后任何 agent/skill/rules/模型变更必须 `make regress` 并留对比表（acceptance §4）。
4. **已知缺陷注入集**：W3 对某证券通信机构真实产物注入 10 条缺陷（+阴性对照），检出 <8/10 时 auditor 不得上线。
5. **supersession**：修订 golden 条目须在 `_meta.supersedes` 记录取代关系，防基线漂移。
6. **项目消歧**：某证券通信机构 ≠ 某证券交易所；某证券交易所重保协防标（20260618 批次）无完整投标文件，不作金标准素材。

## 敏感级

素材原件含投标人（某网络安全服务商）真实材料 → L2。golden 目录只存指针/指纹/结构化标注，**不复制原件**；L3（成本价、证件号）任何情况下不入本目录。
