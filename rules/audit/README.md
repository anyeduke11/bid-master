# rules/audit/ — auditor 规则库（W3 3.1）

> 来源与血缘见 `audit-rules.json` `_meta.source`：bid-file-review v2.5（已在 `~/.agents/skills/` 中标记 deprecated 归档流程，见 plan 3.1）+ BD-0025 基线（教训 L-9）+ 某证券通信机构核对单实证。
> **评测同源**：金标准标注/召回率口径即本库（tests/golden/README）。

## 使用

- bid-auditor 开工时载入 `audit-rules.json`（bid-audit/SKILL.md §1 工艺第 1 步）；按 category 分组扫描，每条命中缺陷仍须带**逐字 cite**（机器复核）。
- `severity` 是建议分级：阻断（废标/★不满足/算术矛盾）/ 严重（负偏离/承诺矛盾）/ 一般（一致性瑕疵）；auditor 拿不准降一级并说明。
- W1 教训已固化进规则（Q-02/Q-03/S-01/C-01/P-01/F-01/X-02/D-01 的 detect 字段标注实例来源）。

## 规则统计

48 条：资格 7 ｜ 废标条款 8 ｜ ★响应 4 ｜ 商务一致 6 ｜ 报价算术 6 ｜ 格式签署 6 ｜ 前后矛盾 5 ｜ 负偏离 4 ｜ 提交电子件 3（含 EXIF/OCR 图片核查挂接点）。

## 变更纪律

规则库属内容级配置：增删改走提案流（.pending → validator → 人确认 → commit）+ `make regress`（auditor 检出率回归）。**只增不删**（教训 L-9：BD-0025 基线逐字保留）。
