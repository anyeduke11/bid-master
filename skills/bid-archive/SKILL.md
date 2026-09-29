---
name: bid-archive
description: bid-archivist 工艺手册——开标后归档提案；只提案不落库；教训 supersession 必填；脱敏红线
version: 1.0.0
version_note: v1.0——desensitize.py 已入 S8→S9 提案闭环（archive-close-proposal 工作流脱敏机检 100% 拦截）+ apply_archive.py 已上线幂等应用：本文件 §3 人工清单降为机检前的自检工序
applies_to: agents/bid-archivist
---

# bid-archive · 归档提案工艺

> 飞轮的入口在你这里：把一标的经历变成下一标能用的教训。但提案经人确认才入库——你不直接写知识库。

## 0. 输入与边界

- 输入：`bids/<id>/` 全目录（阶段产物 / run manifest / audit 记录）+ 开标结果（中标/落标/废标及原因）。
- **落库边界**：产物只有 `bids/<id>/archive/proposal.json` 与 `archive/lessons-draft.md`。**绝不改动 `kb/` 与 `~/.bidmaster/memory/`**——那是 apply_archive + 人工确认（L2→L3）之后的动作。

## 1. 工艺流程

1. **复盘归因**：只依据证据链（阶段产物、run manifest、audit 轮次记录）。无 manifest 的旧标 → 归因标 `evidence=partial`，只提炼有据教训。
2. **教训草案**：每条 `{id, scenario 场景, lesson 教训, evidence 证据, supersession}`——**supersession 必填**：写明"取代哪条旧教训 ID"或"无（新增维度）"，防止教训库自相矛盾。
3. **案例/证照变动提案**：案例带时效标签（金融客户案例只认近 3 年）；证照变动（新证/到期）列清单。
4. §3 脱敏自检。
5. 落盘 proposal.json + lessons-draft.md + **待人工确认清单**（哪些教训建议采纳、哪些案例建议做切片）。

## 2. proposal.json 契约

```json
{
  "bid_id": "2026-xxx",
  "result": "win | loss | no-bid",
  "producer": "bid-archivist",
  "cases": [
    {"name_alias": "<客户别名>", "industry": "<行业>", "year": 2026,
     "scene": ["<适用场景>"], "slices_proposed": ["<建议切片的方案素材>"],
     "valid_until": "<YYYY-MM-DD>"}
  ],
  "cert_changes": [{"cert": "<证照名>", "change": "新增|到期|降级", "affects": ["<影响哪些标的类型>"]}],
  "lessons": [
    {"id": "L-<n>", "scenario": "<场景>", "lesson": "<教训>",
     "evidence": "<产物/manifest 出处>", "supersession": "<旧教训ID | 无>",
     "status": "proposed"}
  ],
  "manual_confirm_list": ["<需人拍板的条目>"]
}
```

## 3. 脱敏自检清单 v0（W2 desensitize.py 上线前人工逐条过）

- [ ] 身份证号 / 手机号 / 证书编号：**0 出现**（索引只存元数据，L3 不落任何提案）
- [ ] 成本价 / 折扣 / 客户名单明细：**0 出现**
- [ ] 客户一律别名+行业表述（二手源先例：东莞银行标 `source=secondary`）
- [ ] 引用产物片段时不含 L3 字段

## 4. 禁止项

- 不修改/删除既有教训（只提案 supersession 关系）。
- 不编造无证据归因；"感觉"不是证据。
- 不替人做采纳决定——lessons 入库需人确认（acceptance §3.6 人工采纳位）。

## 5. 升级路径

| 阶段 | 状态 |
|---|---|
| v0（现在） | 脱敏人工清单；产物留 archive/ 待人工确认 |
| W2 | `rules/desensitize.py` 上线 → 提案 100% 过机检（拦截率要求 100%） |
| W4 | `rules/apply_archive.py` 幂等应用（双跑 no-op）+ lessons supersession 字段；S8→S9 门禁强制：无 proposal + 采纳记录不推进 |
| 变更纪律 | 提案流 + `make regress` |
