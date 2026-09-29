# API 契约矩阵（v0.3.2 现行 → v1 重构基准）

> 用途：server.py 拆包重构（DEV-0042）的前后端一致性对照基准。逐调用点枚举前端/脚本实际消费的 API，
> 从现行 server.py 行为推导响应形状。重构铁律：**读端点响应 = 旧形状超集**（新字段可加，旧字段名/语义不删不改）。
> 原始响应样本冻结在 `tests/golden/api-snapshots/`（2026-09-12 抓取，demo 数据）。

## 一、前端调用点清单（public/index.html）

### 读（getJSON / fetch GET）

| # | 调用点(行) | URL | 消费的响应字段 | 渲染去向 |
|---|---|---|---|---|
| 1 | :600 | 任意 getJSON(url) | — | 通用 |
| 2 | :659 | `/api/views/{name}[/{bid}]`（name∈now/funnel/system） | `{ok, view, data}` | BAW 面板 |
| 3 | :674 | `/api/baw/epoch` | epoch 值 | epoch 戳 |
| 4 | :694 | `/api/baw/bids` | `{ok, bids:[{bid_id,stage,kind,note,updated_at}], schema}` | 管线卡 |
| 5 | :695 | `/api/initial` | `{bids, stats, events, playbooks, flow_template, settings?}` | 首载聚合 |
| 6 | :852 | `/api/baw/bids` | 同 #4 | 管线刷新 |
| 7 | :913 | `/api/baw/alerts` | `{alerts:[...]}` | 告警面板 |
| 8 | :947 | `/api/skills/status` + `/api/initial` | skill 卡数组 | Skill 状态页 |
| 9 | :995 | `/api/leads?recommend=&limit=&sort=&order=&phase=` | leads 数组（含 score/recommend/lifecycle/sales_owner/…） | 商机列表 |
| 10 | :1097 | `/api/digest?date=&force=` | digest markdown/字段 | digest 视图 |
| 11 | :1117 | `/api/summary?period=week\|month\|quarter\|year` | 赢单率/行业/区域/分级/输单原因/Top客户 | 经营汇总 |
| 12 | :1165 | `/api/commands/list` | 命令元数据数组 | 命令注册表展示 |
| 13 | :1185,:1198 | `/api/initial` | events | System 刷新 |
| 14 | :1226 | `/api/bids/{code}` | 单 bid 全字段（见 §三.1） | bid 深潜 |
| 15 | :1227 | `/api/bids`（默认 status=active） | bids 数组 | 看板列表 |
| 16 | :1228 | `/api/stats` | `{total,p0,p1,p2,ready,blocked,total_ai,ready_rate}` | 统计条 |
| 17 | :1229 | `/api/leads?recommend&limit` | 同 #9 | 商机 |
| 18 | :1230 | `/api/health` | `{ok,service,port,bids,events}` | 健康卡 |

### 写（fetch POST/PATCH）

| # | 调用点(行) | 请求 | 响应处理 |
|---|---|---|---|
| 19 | :818 | `POST /api/bids/{code}/{action}`（pause/resume/close/reopen/archive，body `{}`） | `.json().catch(()=>({}))` — 响应被忽略 |
| 20 | :825 | `PATCH /api/bids/{code}/priority`（body `{value}`） | 响应被忽略 |
| 21 | :833 | `POST /api/commands` bid.delete（Idempotency-Key `del-…`） | 忽略，靠刷新 |
| 22 | :843 | `POST /api/commands` bid.create | 忽略 |
| 23 | :973 | `POST /api/skills/run`（`{skill}`） | 忽略 |
| 24 | :982 | `POST /api/playbooks/run`（`{id}`） | 忽略 |
| 25 | :1053 | `POST /api/leads/scan-freshness` | 忽略 |
| 26 | :1062,:1070,:1077 | `POST /api/commands` lead.promote / lead.qualify / lead.patch | 忽略 |
| 27 | :1231 | `POST /api/commands` 通用网关（commandId+params，Idempotency-Key） | 读 `{ok,execution_id,...}` |

SSE：`/api/stream`（EventSource）— 事件形状 `data: {"type","ts","payload"}`（type 含 bid_update/event/p0_alert/epoch…）。

## 二、脚本客户端调用点

| 客户端 | 调用 | 说明 |
|---|---|---|
| scripts/archive_close.py | GET `/api/bids?status=all`；POST `/api/bids/{code}/close`、`/archive` | SSRF 白名单限环回 |
| scripts/bid_dongguan.sh | PATCH `/api/bids/dgyhst2026/{ai_ready,block,human_todo}` | 剧本 |
| scripts/bid_nfh.sh | PATCH `/api/bids/nfh2026/{ai_ready,block}` | 剧本 |
| rules/chase_links.py | POST `/api/commands`（lead.patch） | 补链 |
| rules/import_xlsx_leads.py | POST `/api/commands`（collection.sync）；POST `/api/leads/scan-freshness` | xlsx 导入 |
| scripts/qualify_score.py | **跨进程直写** `~/.bidboard/bidboard.db`（反模式，本轮消除） | 评分回写 |

## 三、v1 端点映射（旧 → 新）

### 读（路径替换，响应形状不变/超集）

| 旧 | 新（/api/v1） | 变更 |
|---|---|---|
| /api/health | /health | 形状不变 |
| /api/initial | /initial | 形状不变（含 flow_template 并入） |
| /api/stats | /stats | 形状不变 |
| /api/bids[?status] | /bids[?status] | **超集**：每个 bid 增加 BAW 字段（bid_id/stage 权威值） |
| /api/bids/{code} | /bids/{code} | 同上超集 |
| /api/leads… | /leads… | 形状不变 |
| /api/leads/closed | /leads/closed | 形状不变 |
| /api/digest | /digest | 形状不变 |
| /api/summary | /summary | 形状不变 |
| /api/logs | /logs | 形状不变 |
| /api/skills/status | /skills/status | 形状不变 |
| /api/playbooks | /playbooks | 形状不变 |
| /api/commands/list | /commands | 形状超集（+参数 schema=智能体能力发现） |
| /api/commands/status/{eid} | /commands/{eid} | 形状不变 |
| /api/baw/bids | （并入）/bids | — |
| /api/baw/alerts | /alerts | 形状不变（去重复死分支） |
| /api/baw/epoch | /epoch | 形状不变 |
| /api/views/* | /views/* | 形状不变 |
| /api/flow/template | （并入 /initial.flow_template） | 独立端点废弃 |
| /api/agent/queue | /agent/queue | 形状不变 |
| /api/stream | /stream | SSE 协议不变 |

### 写（统一命令网关 + 动作端点）

| 旧 | 新 | 说明 |
|---|---|---|
| POST /api/commands | POST /commands | 协议不变（Idempotency-Key/Payload-Hash/X-Agent-Id）+ 新增 artifact.register/promote、run.register 命令 |
| POST /api/bids/{code}/{action} | **废弃** → `bid.lifecycle` 命令 | 前端 #19 改造 |
| PATCH /api/bids/{code}/{field} | **废弃** → `bid.update_field` 命令 | 前端 #20、bid_dongguan.sh、bid_nfh.sh 改造 |
| POST /api/skills/run | POST /skills/run | 形状不变 |
| POST /api/playbooks/run | POST /playbooks/run | 形状不变 |
| POST /api/leads/scan-freshness | POST /leads/scan-freshness | 形状不变（GET 空实现废弃） |
| POST /api/digest/regenerate | POST /digest/regenerate | 形状不变 |
| POST /api/agent/ask / answer | POST /agent/ask / answer | 形状不变 |
| POST /api/reset | POST /reset | 形状不变 |

### 智能体接触面新增（v1 only）

| 端点/命令 | 用途 |
|---|---|
| GET /api/v1/tickets?status= | 工单队列领取（四态机） |
| GET /api/v1/contracts/agents、/contracts/artifacts | 契约发现 |
| GET /api/v1/lessons | 教训只读 |
| GET /api/v1/spec-template | 写作规格单模板 |
| GET /api/v1/bids/{bid_id}/gate | 下一阶段门禁阻塞项查询（set_stage --show 的 HTTP 形态） |
| 命令 artifact.register / artifact.promote / run.register | 产物/运行登记（替代 python3 -c 内联导入） |

## 四、关键响应形状备忘（快照实测）

- **bid（看板形状，24 字段）**：code, name→(client 内), client, stage, priority, tier, industry, region, est_amount, due_at, lifecycle, ltc_stage, lifecycle_history, flow, ai_ready, human_todo, ai_summaries, competitors, partners, decision_maker, loss_reason, block, last_sync, created_at, updated_at
- **baw bid**：{bid_id, stage, kind, note, updated_at}（schema: baw-live-1）
- **stats**：{total, p0, p1, p2, ready, blocked, total_ai, ready_rate}
- **views/***：{ok, view, data}
- **命令成功**：{ok, execution_id, replay?, result...}；失败：{err, execution_id}
- **实测 bug**（v0.3.2 存在，v1 修复）：`ticket.list` → `{"err":"执行异常: name '_ticket' is not defined"}`
