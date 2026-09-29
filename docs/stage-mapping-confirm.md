# 真实标 stage 映射确认表（A4 · 2026-09-11 生成）

> **用法**：以下 stage 是迁移时的机器保守映射（kanban 漏斗语义 ≠ BAW S0–S9 语义），
> 请 owner 逐行核对，把「建议」列改为你认定的真实阶段，回填后我执行 set_stage 修正。
> kanban 原始漏斗态（跟踪/修订/审查/已关闭）与 BAW S0–S9 的语义对照仅作参考，不作依据。

| bid_id | legacy code | kanban 漏斗态 | 迁移映射（当前值） | 建议核对方向 |
|---|---|---|---|---|
| 2026-nfh2026 | nfh2026 | 修订 | S0 | 若已完成解构/规格单，实际应为 S3–S4 |
| 2026-payh26 | payh26 | 跟踪 | S0 | 跟踪期线索，S0 大概率正确 |
| 2026-dgyhst2026 | dgyhst2026 | 修订 | S0 | 同 nfh2026，若解构完成应为 S3–S4 |
| 2026-BB-AUTO-20260816-445729 | BB-AUTO-20260816-445729 | 审查 | S0 | 自动建标的测试/候选线索，核实后大概率「排除」出真实层 |
| 2026-unionpay-intl26-1 | unionpay-intl26-1 | 审查 | S0 | 同上，逐标确认 |
| 2026-unionpay-intl26-2 | unionpay-intl26-2 | 审查 | S0 | 同上 |
| 2026-unionpay-intl26-3 | unionpay-intl26-3 | 审查 | S0 | 同上 |

**签字**：owner 确认后本表归档至 `docs/`，truth.db 按「建议」列批量修正（stage_history 留痕 actor=owner）。
