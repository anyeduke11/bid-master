# rules/ — 确定性门禁与机检（"什么算合格"，唯一强制者）

> AI 生产"资格的 content"，脚本认证"放行的资格"。（设计 §10）
> 铁律：脚本能做的不许做 Agent；本目录不调 LLM。

| 脚本 | 用途 | 挂载点 | 交付 |
|---|---|---|---|
| `hooks/pre-commit` | 产物入 Git 前跑 `make gate` | `.git/hooks/`（`make install-hooks`） | W1 ✅ |
| `set_stage.py` | **S0–S9 状态唯一写入口，§8.2 门禁矩阵内嵌**；拒绝输出卡点清单；`--sign-off` L3 签核；审计留痕 `~/.bidmaster/log/set_stage.log.jsonl` | 看板命令 `bid.advance_stage`（kanban v0.4 注册）/ CLI / ZCode 会话 | W2 ✅ |
| `rebuild_cache.py` | 看板投影 `~/.bidmaster/out/projection.db` 全量重建（完稿标记协议：只认 final/confirmed） | `make rebuild-cache` | W2 ✅ |
| `desensitize.py` | 红线正则（身份证/手机/证书编号）+ 白名单机制；自测 `make selftest` | **S8→S9 门禁已挂**；W4 ingest 转正路径 | W2 ✅ |
| `kb_init.py` | 半自动 kb 初始化（raw 归档 + index draft，保护人工确认条目） | 一次性（W2 2.3 已执行，index 待人工复核） | W2 ✅ |
| 协议文档 `docs/data-plane-protocol.md` | 完稿标记/单一写者/投影/watcher 口径 | watcher（kanban v0.4）| W2 ✅ |
| `bids_consistency.py` | bids.jsonl 一致性：normalize/migrate/check（修双写并存，schema=baw-1）；set_stage 读入即规范化、写前校验 | `make check-bids`；watcher/看板复用 | W2 ✅ |
| `consistency.py` | 人员跨标冲突 / 证照有效期 / 资源挤占 → alerts.json | cron 08:30 | W4 |
| `audit/audit-rules.json` | auditor 弹药库 48 条（源=bid-file-review v2.5+BD-0025+某证券通信机构实证；金标准评测同源） | bid-auditor 开工载入 | W3 ✅ |
| `verify_draft.py` | writer 机检四项：cite 白名单违规=0（硬指标）/评分点覆盖/字数区间/manifest 完整；报告落 verify/（final） | S4→S5 门禁；`--selftest` | W3 ✅ |
| `ticket.py` + `tickets/*.json` | 工单 generate（模板+活数据→queue+可复制 prompt）/list/reconcile（ticket_id 闭环对账）；模板 5 个 | 看板 ticket.generate（v0.4.x）/ CLI | W3 ✅ |
| `writer_contract.json` + `verify_draft.py` | writer 规格单 schema；cite 白名单 / 评分点覆盖 / 字数区间 | S4→S5 | W3 ✅ |
| `verify_audit.py` | auditor cite 逐字复核（审查审查者） | S5→S6 | W3 |
| `validate_leads.py` | scout 产物：evidence 非空 / 去重 / 拒绝带原因 | cron 跟抓取后 | W4 |
| `apply_archive.py` | archivist 提案幂等应用 + lessons supersession | S8→S9 | W4 |
| `ingest.py` | 收割：flock + 内容指纹幂等 + 类型识别（调 desensitize） | cron | W4 |

门禁矩阵（§8.2）：S2→S3 lessons_applied · S3→S4 hits 对账 100% · S4→S5 完整性+评分点全覆盖+素材匹配率 · S5→S6 auditor 阻断=0 + locator≥95% + 人工签核 · S8→S9 apply_archive + lessons 采纳。
