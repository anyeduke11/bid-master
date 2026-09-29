# W2 数据面演示记录 · set-stage 门禁全链路（M2 数据面部分）

> 2026-09-10 · 依据 plan §2（M2 验收）与 design §8.2 门禁矩阵。
> 演示 bid：`2026-demo-w2b`（合成数据，工作区 `~/.bidmaster/bids/2026-demo-w2b/`）。
> 看板 5s 感知：**待 kanban v0.4 改造**（server.py watcher + `bid.advance_stage` 注册，见 plan W2 拆分说明）——本记录覆盖数据面全部能力。

## 一、全链路结果（S3 → S9，16 步：拦截 9 / 放行 6 / 回退拒 1）

| 步 | 迁移 | 场景 | 结果 | 卡点/放行要点 |
|---|---|---|---|---|
| ① | S3→S4 | 缺 hits_recon | ⛔ 拦截 | 指出缺失文件与 schema |
| ② | S3→S4 | 对账条目缺理由 | ⛔ 拦截 | 「态势感知」缺收录理由 |
| ③ | S3→S4 | 补齐理由 | ✅ 放行 | coverage=100%（0ms） |
| ④ | S4→S5 | 缺 completeness/spec | ⛔ 拦截 | 指出缺失文件 |
| ⑤ | S4→S5 | 素材匹配率 0% | ⛔ 拦截 | 0% < 80%（0/5） |
| ⑥ | S4→S5 | 补素材指针 | ✅ 放行 | match_rate=100%（0ms） |
| ⑦ | S5→S6 | 无审计记录 | ⛔ 拦截 | 须先过 auditor 一轮 |
| ⑧ | S5→S6 | round-1 有阻断 | ⛔ 拦截 | 逐条列出阻断缺陷（含 cite）+ 缺 locator + 缺签核 |
| ⑨ | S5→S6 | 阻断清零未签核 | ⛔ 拦截 | **L3 签核不可代签** |
| ⑩ | S5→S6 | `--sign-off Duke` | ✅ 放行 | audit_round=r2, blocking=0（0ms） |
| ⑪ | S6→S7→S8 | 无门禁迁移 | ✅ 放行 | 照常留痕 audit log |
| ⑫ | S8→S9 | proposal 未确认 | ⛔ 拦截 | status='proposed'，须人工采纳（飞轮强制） |
| ⑬ | S8→S9 | 提案含证书编号 | ⛔ 拦截 | **desensitize 命中 2 处**（L3 红线） |
| ⑭ | S8→S9 | confirmed+干净+supersession 完整 | ✅ 放行 | desens_hits=0 |
| ⑮ | — | `make rebuild-cache` | ✅ | bids=5 产物=39（final=2）——删库重建即恢复 |
| ⑯ | S9→S8 | 回退 | ⛔ 拒绝 | 状态只前进 |

原始输出：本轮 `/tmp/w2b-demo-raw.txt`（会话内）；卡点文案与统计以本表为准。

## 二、研发过程如实记录（v1 运行发现 2 个 bug）

1. **门禁早退路径返回 2 元组**（应为 3 元组）→ ①④⑦ 步 `ValueError` 崩溃。修复：10 处早退路径统一 3 元组；用一次性 `probe-s5s6` bid 复测原崩溃路径通过（记录见会话）。
2. **rebuild_cache 对顶层非 dict 的 JSON 崩溃** → 修复：`not-a-dict` 容错并保留指纹。
3. v1 运行的演示 bid（2026-demo-w2）已完成使命，记录与工作区已清理；本轮 w2b 为修复后干净全链路。

## 三、性能实测（2.5）

- 门禁校验耗时：**0–3ms**（全部为工作区小 JSON 读取 + 规则判断；desensitize 挂载的 S8→S9 亦 0–1ms）
- 要求 ≤2000ms：**达标，余量 ~3 个数量级**，无需 stage 元数据缓存。
- 采集方式：`--timing` 输出 `gate_ms`；每次尝试（含拦截）均落 `~/.bidmaster/log/set_stage.log.jsonl`（审计留痕）。

## 四、真实标只读体检（非演示）

对三个存量真实标（2026-GOLD-jishu / 2026-szse-zhongbao / 2026-dgbank-attack，bid-master skill 9 月 9 日产物）**只读**运行 §8.2 门禁函数（不写任何文件）：三个标在 S2→S3 / S3→S4 / S4→S5 全部拦截，卡点精准命中 schema 代差——skill 时代产物缺 `lessons_applied`、`hits_recon.json`、`completeness.json`。
**结论**：门禁对真实数据立即有效；存量标要推进须按 BAW 契约补产物（这正是 W3 各机检的活）。

## 五、发现与遗留

1. **⚠️ 双写者迁移期风险（重要）**：`memory/bids.jsonl` 现存两类记录——skill 时代（`stages` 数组、无 `stage` 字段，由 bid-master skill 会话写入）与 set-stage 时代（`stage` + `stage_history`）。**bid-master skill 与 set-stage 并行运行会破坏单一写者**。缓解：同一 bid 不并行开两个体系的会话；根治：W3 skill 整合时把 skill 的状态写路径改道 set-stage（W3 3.4/3.5 范围）。
   → **2026-09-10 晚更新**：数据层已修复（`rules/bids_consistency.py` 迁移+schema 标签+set_stage 写前校验，DEV-0009）；行为层根治仍归 W3 整合。
2. **看板感知缺口**：`bid.advance_stage` 注册进 server.py + watcher 5s 轮询属 kanban v0.4（plan W2 收尾/跨周期），数据面已就绪。
   → **2026-09-10 晚更新**：kanban v0.4 已交付（见下节），本项关闭。
3. desensitize 白名单机制（`rules/desensitize_allowlist.txt`，当前 2 条公开编号格式）——白名单扩充须走提案流，防"白名单越加越宽"稀释红线。

## 六、kanban v0.4 联调记录（2026-09-10 晚 · M2 验收达成）

**交付**：server.py 增量三处 + 新桥接模块：
- `rules/kanban_baw_bridge.py`：BAW 数据面只读快照（bids.jsonl 规范化读取 + final/confirmed 产物扫描）
- `bid.advance_stage` 命令注册（scope=gate）：进程内调 `set_stage.advance_payload`（无 subprocess），bid_id 白名单校验，拒绝返回卡点清单（rc=2）
- `_baw_watcher_loop`：5s 轮询数据面 → 镜像进看板库 `baw_mirror_bids/baw_mirror_artifacts` → SSE `_broadcast("baw_update")`
- `bid.update_field` 对 stage 字段强制拦截（blocked_by=baw-gate，PRD 宪法）
- GET `/api/baw/bids`：镜像只读视图
- 配套：set_stage 新增进程内接口 `advance_payload()`（CLI advance() 改为其打印包装，行为不变）

**联调结果（9 验证点全绿）**：

| 验证 | 结果 |
|---|---|
| 镜像初值（watcher 首轮） | ✅ 5 标 |
| CLI 推进 → 看板感知延迟 | ✅ **2.1s**（要求 ≤5s） |
| HTTP advance_stage 拦截（缺产物） | ✅ result.ok=False rc=2，卡点清单逐条返回 |
| HTTP advance_stage 放行 | ✅ gate_ms=0，镜像推进 |
| update_field 改 stage | ✅ HTTP 400 blocked_by=baw-gate |
| 回退 S5→S4 | ✅ 拒绝（状态只前进） |
| sign_off 无法绕过门禁 | ✅ 无审计记录仍拦 |
| 非法 bid_id（../../etc） | ✅ HTTP 400 白名单拒绝 |
| 投影重建（make rebuild-cache） | ✅ 与镜像并存互不干扰 |

**研发过程如实记录**：①首版在 handler 内刷新镜像 → 与 `_dispatch_command` 的事务/DB_LOCK 锁竞争 500（15s busy_timeout）→ 修复：handler 内禁写本库，交给 watcher；②server.py 顶层未导入 `re` → `name 're' is not defined` 500 → BAW 段内 `import re as _re`；③响应信封为 dispatch 包装（handler 返回在 `result` 字段），首次验证脚本读错层级。三次均当场定位修复。

**遗留**：看板前端视图（单标深潜页展示 BAW 标/卡点面板）未做——API 已就绪，属 v0.4.x UI 迭代；`stop.sh` 端口检查会把远程 :8080 连接误判为本机占用（非本项目文件，未修）。
