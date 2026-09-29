# bid-master API Reference · /api/v1（DEV-0042）

> 单系统整合后的统一 API 面。前端/脚本/智能体/工作流共用。
> 契约基准：docs/api-contract-matrix.md（前端消费字段逐一枚举）；响应=旧形状超集。
> 写操作 100% 走命令网关；读操作 REST 按域拆分。

## 通用协议

- **Content-Type**: `application/json; charset=utf-8`
- **CORS**: `Access-Control-Allow-Origin: *`（本机看板）
- **SSE**: `GET /api/v1/stream`，帧格式 `data: {"type","ts","payload"}`（type: connected/bid_created/bid_updated/bid_deleted/lifecycle/lead_created/lead_auto_promoted/p0_alert/baw_update/skill_running/agent_request/agent_answer/flow_node/epoch…）

### 命令网关（唯一写通道）

```
POST /api/v1/commands
Headers:
  Idempotency-Key: <业务幂等键，必填>
  Payload-Hash:    <载荷哈希，可选；同 key 异 hash → 409 IDEMPOTENCY_PAYLOAD_MISMATCH>
  X-Agent-Id:      <调用方署名，默认 "duke"；落审计 command_execution.agent_id>
Body: {"commandId": "...", "params": {...}}
响应: {"ok": true, "execution_id": "cmd_...", "commandId": "...", "result": {...}}
     重放: {"ok": true, "replay": true, "_replay": true, ...}
     业务错: 400 {"err": "..."}；未知命令: 404；执行异常: 500
```

审计查询：`GET /api/v1/commands/{execution_id}` → {execution_id, commandId, status, params, result, error, agent_id, created_at, completed_at}

### 命令注册表（20 个，`GET /api/v1/commands` 返回含参数 schema）

| 命令 | scope | params 摘要 |
|---|---|---|
| bid.create | platform | code/client/priority/due_at/industry/region/est_amount…（truth.db 建档 + 看板 profile，kind 按 DEMO_MARKERS 判定） |
| bid.update_field | platform | code + field(block/priority/due_at/client) + value；stage 被拦 → 转 bid.advance_stage |
| bid.add_ai_ready / bid.add_human_todo | platform | code + item |
| bid.lifecycle | lifecycle | code + to(active/paused/closed/archived) + reason/loss_reason |
| bid.flow_node | platform | code + node_id + status(pending/progress/done/blocked) |
| bid.attach_summary | summary | code + text + author + evidence_refs |
| bid.delete | platform | code（truth + profile 物理删除） |
| bid.advance_stage | gate | bid_id + to_stage(S0..S9) + sign_off（S5→S6 必填）；门禁拒绝返回 blockers |
| lead.qualify | platform | lead_id + recommend(P0/P1/P2/跳过) + reason（必填） |
| lead.patch | platform | lead_id + fields{link/sales_owner/phase/recommend/buyer_level/sub_industry} |
| lead.promote | platform | lead_id + new_code |
| collection.sync | collection | items[] + mode(append/upsert) + source；lead_id 缺省按 sha256(title\|buyer) 派生 |
| playbook.run | platform | id(pb-*) |
| ticket.generate / ticket.list / ticket.reconcile | platform | template/bid_id/round/stage；status |
| artifact.register | agent | bid_id + kind + path + status + producer；**自报 final 强制降级 registered** |
| artifact.promote | agent | bid_id + kind + path（指纹未变才提升 final） |
| run.register | agent | agent/bid_id/model/self_check/ticket_id/tokens… |

## 读端点

### meta
- `GET /api/v1/health` → {ok, service, port, bids, events}
- `GET /api/v1/initial` → {bids, stats, events, playbooks, flow_template}（首载聚合）
- `GET /api/v1/stats` → {total, p0, p1, p2, ready, blocked, total_ai, ready_rate}
- `GET /api/v1/bids/summary` → {active, paused, closed, archived, total}
- `GET /api/v1/logs?limit&level&module&code&keyword` → 事件数组
- `GET /api/v1/summary?period=week|month|quarter|year` → metrics/by_industry/by_region/by_tier/by_loss_reason/top_clients
- `GET /api/v1/digest?date&force` → {ok, date, markdown, source(cached/stats_only/yesterday), status}

### bids（超集形状：看板 24 字段 ∪ BAW 权威字段 bid_id/stage/kind）
- `GET /api/v1/bids?status=active|paused|closed|archived|all`
- `GET /api/v1/bids/{code}`
- `GET /api/v1/baw/bids` → {ok, bids:[{bid_id,stage,kind,note,updated_at}], schema:"baw-live-1"}（管线视图数据源）

### leads（观察层，app.db）
- `GET /api/v1/leads?recommend&limit&sort(time|amount|priority|phase|buyer_level|sub_industry)&order&phase`
- `GET /api/v1/leads/closed?limit`（关闭区 freshness=expired，附 days_old）
- `POST /api/v1/leads/scan-freshness`（手动时效扫描）

### BAW 读模型（truth.db 直读）
- `GET /api/v1/views/{now|funnel|system}` → {ok, view, data}
- `GET /api/v1/views/bid/{bid_id}` → 单标深潜（stage_history/gate_attempts/artifacts/verify_summary）
- `GET /api/v1/epoch` → {ok, epoch}（L2 变更版本号）
- `GET /api/v1/alerts` → {ok, alerts}（consistency.py 产出）

### 运行时
- `GET /api/v1/skills/status`、`POST /api/v1/skills/run`（{skill}，202 异步）
- `GET /api/v1/playbooks`、`POST /api/v1/playbooks/run`（{id}）
- `GET /api/v1/agent/queue`、`POST /api/v1/agent/ask`（{code,question,type}）、`POST /api/v1/agent/answer`（{code,field,text}）
- `POST /api/v1/digest/regenerate`（{date}）
- `POST /api/v1/reset`（重播 demo；truth 有 real 标时不播种）

## 智能体接触面（v1 新增）

| 接触面 | 端点 | 说明 |
|---|---|---|
| ①触发 | `GET /api/v1/tickets?status=` | 工单队列领取（四态机） |
| ②输入 | `GET /api/v1/contracts/agents`、`/contracts/artifacts`、`/spec-template`、`/lessons` | 契约/知识发现（lessons 只读——写只经 apply_archive + 人工确认） |
| ③产出 | 命令 artifact.register/promote、run.register | 替代 python3 -c 内联导入；带 X-Agent-Id 审计 |
| ④知识 | 同 ② lessons | |
| ⑤观测 | `GET /api/v1/bids/{bid_id}/gate` | 下一阶段门禁阻塞项查询（set_stage --show 的 HTTP 形态，只读不落 gate_attempt） |

## 废弃端点（v1 中 404）

- `PATCH /api/v1/bids/{code}/{field}` → 用命令 bid.update_field
- `POST /api/v1/bids/{code}/{action}` → 用命令 bid.lifecycle
- `GET /api/v1/flow/template` → 并入 /initial.flow_template
- 旧 `/api/*`（无版本前缀）全部下线；`~/.bidboard` 数据面退役（truth.db + app.db 取代）

## 验证

`make gate`（含 gate-api：tests/test_api.py 36 项契约断言，密封隔离）
