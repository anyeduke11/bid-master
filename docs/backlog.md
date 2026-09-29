# 遗留项与待决清单（BAW v1.0.0 · 滚动维护）

> 规则：各轮"未实现 / 需补充考虑和增强"统一汇入本文件；每条含来源、建议处理时机。完成一条划一条（补完成日期）。
> **2026-09-10 深夜架构审查修复轮（DEV-0018）**：审查 P1-1/2/3/4a/5/6/7 全部修复；测试数据清理完成；真实层（truth.db）上线。join key 决策=冻结 legacy（D1 本义，PATCH 拦截文案已按此落）。

## A. 需 owner 动作的待办

| # | 事项 | 来源 | 建议 |
|---|---|---|---|
| A1 | 金标准人工确认（confirmation-sheet.md：B 类人员表 12 条 + C 类评分点 9 条须对照 PDF；A 类 6 条可优先）——**外部资源阻塞：原件 PDF 不在手**（batch 仅 txt 重铸件），需从阳光平台重新下载（YG26QG0039121 / CGXM-IT-SJ-2026-030） | W1 1.5 | **高优先**——PDF 到手后先跑表格机检预核对，再交 owner 语义确认 |
| A2 | ~~crontab 安装~~ → **已完成并验证（2026-09-11）**：5 条 BAW 任务在 crontab；cron_baw.sh 的 flock（macOS 无此命令）改为 mkdir 原子锁并实测互斥/自清 | W4 4.3 | 关闭；次日 08:30 首次真实触发观察 log |
| A3 | 一天全链路演练（docs/ops-day-drill.md runbook） | W4 4.6 | 需一个真实工作日 + A2 |
| A4 | stage 映射确认表已生成（docs/stage-mapping-confirm.md）：7 旧标逐行列出待 owner 签字 | W4 | 择时签认，回填后批量修正 truth.db |
| A5 | ~~ingest 首次全量收割~~ → **已完成（2026-09-11）**：lingxi-claw 4572 + workbuddy 6788 全量入 inbox（脱敏拦截 2477 件入 rejects） | W4 4.2 | 关闭；rejects 抽查归 B 类 |
| A6 | ~~audit-r1 存疑 W2~~ → **已解决（2026-09-11）**：tender 原文 [P913]/[P904] 本身即"原则上不能更换"措辞——草稿忠实转述无缺陷；W2 消除 | W3 3.5 | 关闭 |
| A7 | **升级 rules/ 后重启 server**（进程内 import set_stage，长跑期间 git pull 后内存是旧门禁）——已写 ops-cron.md | DEV-0012 风险 | 记住即可 |

## B. 开发遗留（滚动）

| # | 事项 | 来源 | 状态/计划 |
|---|---|---|---|
| B3' | lead_capture 实抓验证（移植后未跑真实渠道） | W4 4.1 | 下个抓取窗口 |
| B4' | people/certs 数据录入（consistency 无数据可查） | W4 4.4 | 随 kb 录入 |
| B10 | v0.6 收尾：读方（watcher/rebuild/regress）从 jsonl 兼容导出切读 truth.db；jsonl 退役 | truth-layer-plan | v0.6 |
| B11 | apply_archive / ticket.reconcile 改写 store（lessons/tickets 表已建，仍写 md/jsonl） | truth-layer-plan | 下轮 |
| B12 | 组合判定合并计分细则（LLM 命中 ∪ 机检命中）实例固化 | DEV-0017 | 首个真实标 |
| B13 | locator-report samples schema v2 的 agent 侧落位（bid-locate SKILL §2 已提；正式抽查起生效） | P1-3 配套 | 下次 locator 任务 |

## C. 风险备忘（持续观察）

| # | 事项 | 说明 |
|---|---|---|
| C1 | ~~双写者~~ **已根治（v0.5.0）**：旧 skill 退役（_retired-bid-master + RETIRED.md）；状态唯一写口=store.py（truth.db 事务+busy_timeout） | 关闭 |
| C2 | 项目安全结论 | Mimosa deep scan（findingCount=0，seal 在案）；提交门禁持续提示"扫描覆盖不完整"——不据此宣称项目安全 |
| C3 | 异档去相关不成立 | auditor=Flash 定版；组合判定（LLM+机检）已接进门禁（v0.5.0）；非 GLM 家族接入时重测 |
| C4 | CronCreate 交付时延分钟级 | 当日任务一律人工；自动消费仅限隔夜批 |
| C5 | token 成本 | 累计实测约 110 万 tokens（子智能体）；超预算压 Flash 批量 |
| C6 | bootstrap 逃生舱 | 非门禁通道（kind 标注+审计留痕）；单用户摩擦机制，不宣称访问控制 |

## 已关闭（2026-09-10 深夜架构修复轮，DEV-0018）

- ~~P1-1 旧 skill 双写~~ → 退役至 `~/.agents/skills/_retired-bid-master`（RETIRED.md 记录承接关系）
- ~~P1-2 机检未接线~~ → gate_s4_s5 消费 verify_draft、gate_s5_s6 消费 verify_audit（20/20 安全带测试实证）
- ~~P1-3 hit_rate 自声明~~ → samples 列表复算，自报数字不采信（与复算不符也拦）
- ~~P1-4a PATCH 旁路~~ → do_PATCH + _set_field 双层拦截（400 baw-gate，实测）
- ~~P1-4b join key~~ → 定版冻结 legacy（D1 本义，不建映射）
- ~~P1-5 门禁零测试~~ → tests/test_set_stage.py 20 断言挂 make gate（gate-tests）
- ~~P1-6 无进程锁~~ → truth.db BEGIN IMMEDIATE + busy_timeout（store 唯一写口）
- ~~P1-7 injectAgentsMd 漂移~~ → 设计表格实况化（开）+ AGENTS.md 第 8 条消歧（只读智能体豁免 DEV_LOG 义务）
- ~~P2 watcher key count~~ → 改 artifacts 全列表（指纹级变更感知）
- ~~测试数据混居~~ → 真实层 kind=demo 全清（truth.db real=3），工作区归档 ~/.bidmaster/sandbox/，jsonl 重导出 3 行
