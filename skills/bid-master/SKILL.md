---
name: bid-master
description: 主 Agent 五阶段语义主链路工艺手册（v1.0 · P0-5）——解构/规格单/关键件/价格/审查闭环；单上下文铁律
version: 1.0.0
version_note: v1.0（P0-5 落地）——承接自退役 skill（~/.agents/skills/_retired-bid-master，见其 RETIRED.md）；完成条件与 contracts/gate-matrix 同源
applies_to: 主 Agent（ZCode 会话，无 .md agent 定义——本手册即会话工艺书）
---

# bid-master · 主 Agent 五阶段工艺手册

> 你是语义主链路的唯一承载者（D7 单上下文铁律：解构/规格单/关键件/价格**禁止派发子智能体**）。
> 子智能体只做分工写作（writer）、抽查（locator）、对抗审查（auditor）、归档（archivist）、初筛（scout）。

## 0. 开工三件事（每次会话）

1. Read `~/.bidmaster/memory/lessons.md`，通读全部 active 教训；
2. 确认标的真实层状态：`python3 rules/set_stage.py --bid <bid_id> --show`；
3. 生成工单或确认 ticket_id（`python3 rules/ticket.py generate --template new-bid-analysis --bid <bid_id>`）——**所有产物 manifest 回填 ticket_id**。

## 1. 五阶段流程与产物（contracts/artifact/ 契约化）

| 阶段 | 你做什么 | 产物（契约文件） | 门禁 |
|---|---|---|---|
| S2 决策 | 商机评估：内定/陪标信号（只提示不下结论，L-7）、资质差距、参与性建议 | `data/stage0.json`（含 lessons_applied） | S2→S3 |
| S3 解构 | 关键词台账**零遗漏**（L-4）、★/▲符号族同扫（L-5）、响应矩阵、评分点抽取 | `data/hits_recon.json` + `data/response_matrix.json` | S3→S4 |
| S4 编制 | 写作规格单（schema v2 八要素，模板 `rules/spec-template-v2.json`）+ **关键件亲写**（投标函/商务偏离表/资质响应表/价格策略）+ 派发 writer 分章 | `data/completeness.json` + `data/spec.json` + 派发工单 | S4→S5 |
| S5 审查 | 驱动 auditor round-N 循环、处理阻断、落盘审计报告 | `audit/audit-rN.json` + `verify/verify_audit_rN.json` | S5→S6 |
| S6 封标 | 渲染终稿包（render 管线） | final_pack/ | — |

## 2. 产物落盘后立即登记（融合纪律一）

每个产物写盘后**立即**执行，不留"稍后统一登记"：

```bash
python3 - <<'EOF'
import sys; sys.path.insert(0, 'rules')
import store
store.init()
print(store.register_artifact('<bid_id>', '<kind>', '<产物路径>', status='final', producer='main-agent'))
print(store.register_run(agent='main-agent', bid_id='<bid_id>', model='GLM-5.3',
      ticket_id='<ticket_id>', self_check='pass'))
EOF
```

未登记的产物会被 `make gate` 的 reconcile 抓为漂移（v1.0-p0 实证）。

## 3. 关键件纪律（篇幅 20%，风险 100%）

投标函、商务偏离表、资质响应表、价格策略说明**必须亲写**：
- 承诺值（响应时间/年限/比例/金额/人数）与招标要求逐字对照（教训 L-1：单段内引文+引号字形）；
- 每个数值标注来源 [P#]；
- 写完自查一遍 rules/audit 的 D 系列（负偏离）与 X 系列（前后矛盾）。

## 4. 完成条件（与 contracts/gate-matrix.json 同源，勿手抄）

每阶段"什么算做完"以 `contracts/gate-matrix.json` 的 requires 为唯一权威；本手册不复述数值阈值（避免双源漂移）。推进一律走：

```bash
python3 rules/set_stage.py --bid <bid_id> --to S<N> [--sign-off Duke]
```

被拦时卡点清单逐条处理后重推（拒绝时 exit 2，全部尝试已留痕审计日志）。

## 5. 子智能体派发（分工写作制）

- writer：按 `rules/spec-template-v2.json` 规格单分章派发（可 run_in_background 并行）；规格单**先落盘再给路径**（writer 无法对内嵌文本算指纹）；
- auditor：工单 audit-round；报告由你落盘 `audit/audit-rN.json`（ticket_id 回填）；
- locator：产物落盘后抽查；报告 samples schema v2（含逐条 hit）；
- archivist：S8 后归档提案 → 你确认 confirmed → `rules/apply_archive.py --bid <id>`。

## 6. 禁止项

- 禁止直写 `~/.bidmaster/memory/bids.jsonl`（真实层唯一写口=store；jsonl 已 deprecated）；
- 禁止跳过 set_stage 直接改状态；禁止代签 `--sign-off`；
- 禁止派发子智能体做语义解析（D7）；禁止 L3 材料进任何 prompt（§14 红线）。
