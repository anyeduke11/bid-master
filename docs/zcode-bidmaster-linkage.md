# ZCode ↔ bid-master 联动与通信机制（DEV-0059）

> bid-master 对 AI 会话暴露三条通道。优先级口诀：**读用 MCP/CLI，写走命令管道，工作流用脚本**。

## 三条通道

| 通道 | 入口 | 适用场景 | 依赖 |
|---|---|---|---|
| **MCP**（原生工具） | `.zcode/config.json` → `mcp.servers.bid-master`（stdio，自动连接） | ZCode 会话内以 `mcp__bid-master__*` 工具直接查询/推进，免 curl/脚本记忆 | 重启会话生效 |
| **CLI**（人机两用） | `~/bid-master/bid <子命令>` | 终端操作、脚本集成、cron；与 MCP 共用同一实现层 | 仅 python3（stdlib） |
| **HTTP + SSE** | `http://127.0.0.1:8080/api/v1/*` | 看板前端、外部系统、实时事件流 | `start.sh` 起服务 |

另有第四条既有通道：**workflow/agent 直调 `rules/*.py`**（.zcode/workflows 编排层专用，不走 HTTP）。

## bid CLI 子命令（16 个）

```
status / bids / show / probe / advance / settle / tickets / lessons
leads / capture / digest / cmd / serve / gate / mcp / help
```

常用示例：
```bash
bid status                                   # 漏斗 + 开放工单 + 服务健康
bid probe 2026-REAL01-aqfw S6              # 只读：推进 S6 会卡什么
bid advance <bid> S5 --ignore-material "原因"  # S4→S5 素材门禁忽略放行
bid advance <bid> S6 --sign-off Duke         # L3 签核（仅 owner）
bid settle <bid>                             # 材料补齐复验销单
bid serve restart                            # 服务管理（委托 start.sh）
```

## MCP 工具（12 个）

只读：`bid_status` · `bid_list` · `bid_show` · `bid_gate_probe`（门禁探针）· `ticket_list` · `lesson_list` · `digest` · `lead_list`
写入：`bid_advance` · `bid_settle_material`（经 set_stage 同门禁同审计）· `capture_run`（走看板异步触发）· `kanban_command`（13 条注册命令管道）

## 安全模型

- **单一写口不变**：MCP/CLI 的写操作全部落到 `rules/set_stage.py` 与 `/api/v1/commands` 命令管道——与看板按钮同门禁、同审计、同幂等；AI 权限不比命令行大。
- **本机白名单**：所有看板 HTTP 走 `rules/kanban_post.py`（仅 127.0.0.1:8080 + `/api/v1/` 前缀）；MCP server 自身零 urlopen、零 subprocess（安全原语全部在既有被审查基建内）。
- **入参收口**：bid_id 正则白名单、to_stage 枚举、自由文本限长拒控制字符。
- **L3 红线不受影响**：S5→S6 `--sign-off` 人工签核位 AI 不可代签（工具会如实拦截）。

## 注册与生效

1. 工作区配置已写入 `.zcode/config.json`（schema 严格，字段：type/command/args/cwd/timeoutMs，绝对路径）。
2. **重启 ZCode 会话**后自动连接；状态在 Settings → MCP 查看。
3. 用户级全局可用：把同结构复制到 `~/.zcode/cli/config.json` 的 `mcp.servers`（注意用户级覆盖工作级同名）。
