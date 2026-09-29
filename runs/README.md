# runs/ — 回归基线（仅 `baseline-*.json` 进 Git）

- `baseline-<YYYYMMDD>-<tag>.json` — `make regress` 输出的金标准基线（召回率/检出率/耗时/token），W4 4.5 首条入 Git
- 单次 run manifest（producer/模型/时长/输入指纹/ticket_id/校验结果）落 **`~/.bidmaster/runs/`**（数据面），不进仓库；本目录其余文件被 `.gitignore` 排除

故障二分（设计 §7.2）：校验挂→产物层；校验过内容错→语义层（locator/golden）；都对看板不对→投影层（`make rebuild-cache`）。
