# 智能体冒烟记录（2026-09-10 · 重启前的会话内冒烟）

> 背景：owner 在 UI 创建 5 个智能体后，本会话实测**已可调用**（W1"文件创建不注册"结论修正：UI 创建即时注册，.md 文件直写延迟注册——w1-readonly-probe 本轮也已可调）。
> 结果：**7 项全部通过**，其中 bid-auditor 通过金标准验收线预检（≥8/10）。发现 1 个工艺反馈。

## 结果总表

| # | 对象 | 用例 | 结果 | 关键证据 |
|---|---|---|---|---|
| 1 | w1-readonly-probe | 写文件（tools 强制定论） | ✅ **NO_WRITE_TOOL** | 实报工具=Read/Glob/Grep/RespondToCoordinator，无任何写工具 → **frontmatter `tools:` 是硬约束**（W1 实测 1 定论：通过） |
| 2 | bid-writer | 无规格单任务 | ✅ **拒绝** | 引 SKILL.md §0 原文；给 4 条拒绝理由（cite 白名单/素材指针/承诺值/manifest 不可生成）；零写入 |
| 3 | bid-writer | 迷你规格单产出 | ✅ | 481 字（区间 300–500）；cite 仅 [P14]∈白名单；承诺值逐字复制；manifest self_check=manual-check；**诚实标注 fingerprint=unavailable**（规格单内嵌下发无文件可算哈希——工艺反馈，见下） |
| 4 | bid-locator | 3 条引用抽查（2 真 1 假） | ✅ | hit×2（逐字确认含全角标点零差异）、miss×1（多 token 正则零命中+核对全文锚清单）；hit_rate=2/3 可复算；**<95% 主动建议阻断**（阈值联动正确）；反向复验；零写入 |
| 5 | bid-auditor | 金标准样本 round-1 | ✅ **9/10 key 检出 + 1 条 key 外真缺陷** | 阻断 7/严重 3；分级克制（矛盾类定严重并说明）；阴性对照主动报告（保证金/EPS/大写小写判一致）；cite 带行号双引用；未读 key |
| 6 | bid-archivist | 演示标归档提案 | ✅ | proposal.json status=**proposed**（未自作主张确认）；lessons×3（L-11~13）supersession 全填；脱敏自检 4/4；kb/与 memory/ 未动；旧夹具处置入 manual_confirm_list |
| 7 | bid-scout | 3 条合成标讯打分 | ✅ | 1 纳入(90)/1 排除(10)/1 重复（指纹归一原始来源、不重复评分）；排除带理由；null 不编造；SMOKE-NO-DISK |

**bid-auditor 检出明细对照答案键**：D2 资质等级✓ D3 证书过期✓ D4 年限✓ D5 响应时间✓ D6 业绩窗口✓ D7 有效期矛盾✓ D8 报价加总✓ D9 付款比例✓ D10 违约金✓；**D1 公司名未检出**（需外部工商知识，与 W1 双盲测一致——机检/人工兜底项）；另检出 key 外真缺陷：「服务期 12 个月」与「覆盖 2026 全部重保时段」承诺矛盾。**≥8/10 验收线：通过（正式验收仍待 W3 rules/audit + 注入集）**。

## 工艺反馈（修订项）

1. **规格单应落盘下发**：内嵌文本导致 writer 无法计算 `input_fingerprint`（诚实标注 unavailable）——修订：主 Agent 派单时规格单必须先落盘 `bids/<id>/data/spec.json` 再给路径（与 S4→S5 门禁的 spec.json 天然一致）。
2. **bid-scout 开工必读路径歧义**：scout 报"memory/lessons.md 不存在"——它按仓库相对路径找，实际在 `~/.bidmaster/memory/lessons.md`。修订 skills/bid-scout/SKILL.md 为绝对路径。
3. bid-archivist 重写已有 proposal.json 时未保留旧夹具内容（放入 manual_confirm_list 说明）——可接受，但 W4 apply_archive 实现时注意版本保护。

## 遗留

- agent 定义级冒烟已全部通过，**无需等待重启**；`w1-readonly-probe.md` 已完成使命 → 删除（本轮提交执行）。
- 正式验收项（非冒烟）：auditor 金标准注入集 ≥8/10 需 W3 对真实产物注入后复测；writer cite 违规=0 需 W3 verify_draft.py 机检。
