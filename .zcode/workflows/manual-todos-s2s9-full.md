# 人工位手册 · bid-flow-s2s9-full

以下事项**有意留给人工**（grill 答案决定），工作流不代办：

- [ ] 材料补录：ch-F 同类项目业绩（占位段替换为实证，删除防误递交声明框）
- [ ] 材料补录：ch-G 人员持证（占位段替换为实证，删除防误递交声明框）
- [ ] 材料补录：ch-H CNNVD 证书（占位段替换为实证，删除防误递交声明框）
- [ ] 材料补录：ch-I CNITSEC/CCRC 资质（占位段替换为实证，删除防误递交声明框）
- [ ] S5→S6 签核：python3 rules/set_stage.py --bid <bidId> --to S6 --sign-off <姓名>
- [ ] S6→S8 开标：现实事件人工出席；开标后触发后程 bid-archive-<slug>（args: bidId/result/reason）
- [ ] 归档采纳：apply_archive --bid <bidId>（人工确认后执行）
