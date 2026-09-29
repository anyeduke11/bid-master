# skills/ — 工艺手册层（"怎么干"）

> 创建方案已定稿：`docs/zcode-agents-and-skills-plan.md`（2026-09-10）。五个子 skill 已于 DEV-0052（2026-09-15）升 **v1.0.0**——机检契约全部上线并被门禁接线，v0 降级条款作废。

角色包四件套之一（设计 §7.1）：`agents/<role>.md`（谁）→ **`skills/<skill>/SKILL.md`（怎么干）** → `rules/*_contract.json`（什么算合格）→ `kb/slices/…`（用什么料）。

| skill | 服务对象 | 状态 |
|---|---|---|
| `bid-write/` | bid-writer：按规格单逐章扩写 + 自检清单 | **v1.0**（verify_draft.py 已接线 S4→S5 门禁） |
| `bid-locate/` | bid-locator：P0 条目二次定位抽查（只读纪律） | **v1.0**（机检接管：verify_draft/verify_audit 逐字复核 + set_stage 阻断） |
| `bid-audit/` | bid-auditor：对抗审查（§1 加载 `rules/audit/audit-rules.json` 48 条，内置六类表兜底） | **v1.0**（规则库 + verify_audit.py 已接线 S5→S6） |
| `bid-archive/` | bid-archivist：归档提案（supersession/脱敏） | **v1.0**（desensitize 入 S8→S9 闭环 / apply_archive 幂等应用已上线） |
| `bid-scout/` | bid-scout：标讯初筛打分契约版 | **v1.0**（validate_leads 已上线：cron + 工作流闭环） |
| `bid-master/` | 主 Agent 五阶段流程书（2026-09 自 `~/.agents/skills/` 迁入仓库；用户级旧版已退役为 `_retired-bid-master`，禁止按其旧协议直写数据面） | v1.0.0 |
| ~~`w1-test-contract/`~~ | W1 实测项 4 夹具（契约已验证，实测 4 ✅） | 已删除（证据存 `log/w1-verify.md`） |

v1.0 约定：机检为准（退出码 + 门禁强制），SKILL.md 人工清单作为工艺依据与机检前的自检工序；`manual-check` / `evidence=partial` / `legacy-format` 标注仅在机检不可用时按降级声明使用。

纪律：agent prompt 第一条写死"开工先 Read 本 skill 的 SKILL.md"（W1 实测 4 ✅）；skill 变更走提案流并 `make regress`（acceptance §4）。
