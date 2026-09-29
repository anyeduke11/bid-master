# kb/index/ — 分域索引（契约，进 Git）

五个分域小 JSON，主 Agent 可全读做匹配（D10 消费走指针）：

| 文件 | 域 | 消费场景 |
|---|---|---|
| `certs.json` | 公司资质/证照 | 阶段 0 硬条件机检（precheck_auto）· 资产台账到期预警 |
| `people.json` | 人员（别名+角色+持证） | 人员跨标冲突（consistency.py）· 规格单人员指针 |
| `cases.json` | 业绩案例 | 规格单素材指针 · 金融客户只认近 3 年（衰减） |
| `solutions.json` | 方案素材 | 规格单素材指针（`slices/…#L…`） |
| `bids_history.json` | 历史投标 | archivist 归档回流 · lessons supersession |

统一结构：`{"_meta": {domain, version, item_fields, updated_at, rule}, "items": [...]}`；每条 item 必含 `file`（指针）/ `fingerprint`（sha256）/ `sensitivity`（L1/L2；L3 不入索引）/ `updated_at`。

`make gate` 校验全部可解析；W2 2.3 从现有资产录入 v1。
