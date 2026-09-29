# 数据面协议（W2 2.2 · watcher 完稿标记协议）

> 依据 design §9（三条接口铁律）/§11、PRD §5/§8。本文件是 watcher、rebuild_cache、kanban v0.4 适配层的共同口径。

## 1. 唯一事实源与单一写者

| 数据 | 唯一写者 | 其他人 |
|---|---|---|
| `~/.bidmaster/memory/bids.jsonl` 的 stage | `rules/set_stage.py` | 只读（含看板） |
| `bids/<id>/` 工作区 | 该标的 ZCode 会话（同 bid 单会话铁律） | 只读 |
| `kb/`、`memory/lessons.md` | `apply_archive` + 人工确认后 | 只读 |
| 线索暂存 | bid-scout | 只读 |
| 看板投影 `out/projection.db` | `rules/rebuild_cache.py`（可随时删库重建） | 只读 |

外部工具目录（lingxi-claw / WorkBuddy / Trae）BAW 只读收割，永不写入。

## 2. 完稿标记协议（status=final）

- 阶段产物落 `bids/<id>/{data,audit,verify,archive}/<name>.json`，**顶层 `"status":"final"` 才被投影/watcher 消费**；
- `archive/proposal.json` 的终稿标记为 `"status":"confirmed"`（人工采纳位，L2→L3）；
- `draft/` 是过程态，永不进投影；
- 产物必须携带 run manifest 字段（producer/model/duration_s/input_fingerprint/ticket_id/self_check）——缺 manifest 的产物不计入统计（acceptance G2）；
- 非法 JSON 的产物在投影中标 `invalid-json` 并保留指纹，供故障二分。

## 3. 投影与感知

- 投影库 `~/.bidmaster/out/projection.db`（表：`projection_bids` / `projection_artifacts`），由 `make rebuild-cache` 全量重建——**删库重建即恢复**，证明看板不拥有状态；
- **watcher 已实现（kanban v0.4，2026-09-10）**：server.py 内 `_baw_watcher_loop` 5s 轮询 `~/.bidmaster/`，按本协议只挑 final/confirmed，镜像进看板库 `baw_mirror_bids/baw_mirror_artifacts` 并 SSE 广播 `baw_update`；实测感知延迟 2.1s；
- 只读视图 `GET /api/baw/bids`；冷恢复 `make rebuild-cache`（projection.db）与镜像表并存、互不干扰；
- kanban v0.4 命令：`bid.advance_stage`（scope=gate，进程内调 set_stage `advance_payload`，拒绝返回卡点清单）；`bid.update_field` 的 stage 写路径已强制拦截（blocked_by=baw-gate）。
- 待 v0.4.x：前端单标深潜页展示 BAW 标与卡点面板（API 已就绪）。

## 4. 状态推进

- 唯一入口 `rules/set_stage.py`：逐级、只前进；门禁矩阵内嵌（§8.2）；拒绝输出卡点清单（exit 2），放行写 bids.jsonl（exit 0）；
- 全部尝试（含拦截）留痕 `~/.bidmaster/log/set_stage.log.jsonl`（审计要求，PRD §8）；
- S5→S6 必须带 `--sign-off <姓名>`（L3 审批位）；S8→S9 强制脱敏机检 + proposal confirmed（飞轮门禁）。
