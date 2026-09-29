# 真实层方案（truth layer · v0.5.0 · 2026-09-10 定稿）

> 依据：Arch-Enginer 架构审查（P1-1/2/3/4/6/7 + 测试数据混居）+ owner 三项指令（skill 写入改造 / llm-wiki 生产 / 数据库真实层 / 按建议修复 / 清理测试数据）。
> 约束：SQL 一律参数绑定（安全约束）；文件层不废——降级为"生产层"。

## 一、分层原则（第一性重述）

**真实层（truth.db）= 权威状态**：状态与登记事实只此一份，事务 + 行锁 + CHECK 约束 + busy_timeout（进程级并发安全，取代 jsonl 无锁写）。
**生产层（bids/<id>/ + memory/）= llm-wiki 式产物**：人可读、agent 可读、可 crystallize/supersession/衰减的知识资产（D9 不变）——由会话生产，**写后必须登记**进真实层才被体系承认。
**写入纪律（唯一不变式）**：智能体（主 Agent / 5 子智能体）一律 **经 skill 的脚本 API（rules/store.py）写真实层**；不再有"skill 直接写文件即生效"的路径；jsonl 降级为真实层的**兼容导出**（老读方过渡用，v0.6 移除）。

```
智能体 + SKILL.md ──调用──▶ rules/store.py（唯一写口，参数绑定 SQL）
                               │ 写 truth.db（bids/stage_history/artifacts/lessons/tickets）
                               ├─▶ 导出 memory/bids.jsonl（兼容投影，generated_from=truth.db）
                               └─▶ 生产层文件由会话产出后 register_artifact() 登记（复算指纹）
门禁/看板/watcher/regress ──读──▶ truth.db（权威）+ 生产层文件（内容校验）
```

## 二、truth.db 表设计（全部参数绑定）

| 表 | 字段 | 要点 |
|---|---|---|
| bids | bid_id PK, stage CHECK(S0..S9), **kind**('real'/'demo'/'test'), bootstrapped, note, created_at, updated_at | kind 字段根治测试数据混居：正式视图只看 real |
| stage_history | id PK, bid_id FK, from_stage, to_stage, ts, sign_off, gate_ms | 不可变追加 |
| artifacts | id PK, bid_id FK, kind(data/audit/verify/archive/draft), path, fingerprint, status(registered/final/confirmed), registered_at | 登记制取代"文件自声明即生效"；指纹由 store 复算 |
| lessons | id PK(L-N), scenario, lesson, supersession, status(active/沉淀), created_at | apply_archive 改写此表（md 由导出生成，保持 llm-wiki 可读） |
| tickets | ticket_id PK, type, status, bid_id, created_at, executed_at, consumed_at | reconcile 消单在此 |

## 三、改动清单（按审查 P1 对应）

| 来源 | 改动 | 文件 |
|---|---|---|
| P1-1/指令1 | 旧 skill 退役：`~/.agents/skills/bid-master` → `_retired-bid-master`（README 记录）；语义主链路=主 Agent + skill 承接，**其写路径全部改道 store API**（建档/推进=store.create_bid/advance） | 文件系统 + retired README |
| 指令1 | rules/store.py 新建（唯一写口）；set_stage 改为调 store（advance_payload 不变签名）；bids_consistency 读侧改读 truth.db（首次启动从 jsonl 单向导入） | rules/store.py、set_stage.py、bids_consistency.py |
| P1-2 | 机检接线：gate_s4_s5 要求全部章节 verify_draft 报告 pass；gate_s5_s6 要求最新轮 verify_audit 报告 pass | set_stage.py |
| P1-3 | locator-report schema 升级 samples:[{quote,hit}]；门禁**复算** hit_rate=hits/len（旧格式无 samples → blocker 提示升级） | set_stage.py + bid-locate SKILL |
| P1-4a | SPA PATCH stage 旁路拦截：`_set_field` 加 baw-gate 同款拦截 | server.py |
| P1-4b | join key 决策：**推荐冻结 legacy**（D1 本义）——不建 code↔bid_id 映射，legacy kanban 标只读冻结，BAW 标独立生命周期；拦截提示不再把 code 当 bid_id | server.py 提示文案 |
| P1-5 | tests/test_set_stage.py：拦截/放行/回退/bootstrap/机检接线五组断言，挂 make gate（gate-tests 目标） | tests/ + Makefile |
| P1-6 | 并发安全由 truth.db 解决：BEGIN IMMEDIATE + busy_timeout=15s（SQL 参数绑定） | store.py |
| P1-7 | injectAgentsMd 实况化：设计表格改"开（owner 定版）"；项目 AGENTS.md 加消歧句"只读智能体豁免 DEV_LOG 义务" | baw-design §4.1 + AGENTS.md |
| P2 顺带 | baw_watcher 变更 key 改 artifacts 全 list（非 count）；ops-cron.md 补"升级 rules 后重启 server" | kanban_baw_bridge.py、ops-cron.md |
| 指令3 | 测试数据清理：demo/test 标（2026-demo-w2b、2026-kanban-demo、2026-smoke-arch、2026-smoke-writer）**不入真实层**（迁移时 kind 判定）；工作区迁 `~/.bidmaster/sandbox/` 留档后从 bids/ 移除；smoke 产出的 L-11~13 教训保留（有效知识）；verify 报告等夹具随 sandbox 迁走；log/*.md 演练记录不动（历史档案） | 迁移脚本一次性 |

## 四、迁移与兼容

1. 首次运行 store.init()：truth.db 不存在 → 从 memory/bids.jsonl 单向导入（bid_id 含 demo/smoke/kanban-demo → kind=demo，其余 real）；此后 jsonl 每次 store 写后重新导出（标 generated_from）。
2. 读方：watcher/rebuild_cache/regress 过渡期读 jsonl 不变（导出格式兼容）；v0.6 切读 DB。
3. server.py advance_stage 不改调用方式（仍 import set_stage → store），**升级 rules 后需重启 server**（写进 ops）。
4. 回退路径：truth.db 损坏 → 删库重跑导入（jsonl 仍在），单一事实源的可重建性质保留。

## 五、验收

- make gate（含新增 gate-tests）全绿；make regress 基线不退化；
- 演示（sandbox 标）：门禁拦/放各一、机检接线生效（无 verify 报告 → blocker）、PATCH stage 双通道全拦、并发双写事务安全（两个进程同时 advance，一个成功一个 busy 等待后拒绝跳级）；
- 真相源 0 测试数据（`SELECT bid_id FROM bids WHERE kind='real'` = 3 个真实标）；
- 版本 v0.5.0。
