# BAW · bid-master 工程入口
# 设计依据：docs/baw-design-v3.md §10（强制机制）、docs/acceptance-agents.md §5（验收命令速查）
#
#   make gate            全量门禁（pre-commit 同套；W2 起 set-stage 内嵌同套校验）
#   make regress         金标准回归（rules/regress.py）
#   make install-hooks   把 rules/hooks/pre-commit 装进 .git/hooks/
#
# DEV-0081：调度已迁服务内置（start.sh 起服务即 3h 一轮，GET /api/v1/scheduler 查看）；
#   crontab/launchd 周期任务已清退；rebuild-cache/check-bids 化石目标已删。
#
# 约定：gate 只做确定性机检，不调 LLM；每个子目标失败即整体失败（安全带不打折）。

PY      ?= python3
SHELL   := /bin/bash
.DEFAULT_GOAL := help

PY_FILES   := $(shell git ls-files '*.py' 2>/dev/null)
JSON_FILES := $(shell git ls-files '*.json' 2>/dev/null)
AGENT_MDS  := $(wildcard .zcode/agents/*.md)

.PHONY: help gate gate-syntax gate-json gate-agents gate-hygiene gate-tests gate-truth gate-skills regress install-hooks install-capture selftest

help:
	@echo "bid-master · BAW 工程入口"
	@echo "  make gate            全量门禁（语法 / JSON / agent 定义 / 仓库卫生 / 门禁安全带测试）"
	@echo "  make regress         金标准回归（rules/regress.py：静态门+基线对比）"
	@echo "  make install-hooks   安装 pre-commit → make gate"
	@echo "  make install-capture 安装标讯抓取依赖（crawl4ai + playwright + openpyxl）"
	@echo "  make selftest        脱敏机检自测（desensitize 两样本）"
	@echo "  调度：服务内置 3h 一轮（./start.sh start；GET /api/v1/scheduler）——无系统级定时任务"

gate: gate-syntax gate-json gate-agents gate-hygiene gate-tests gate-api gate-truth gate-skills
	@echo "✅ gate PASS"

# 1) 所有纳管 .py 可编译（含 rules/ 与 tests/ 下的脚本）
gate-syntax:
	@echo "▶ gate-syntax: $(words $(PY_FILES)) 个 .py"
	@$(PY) -m py_compile $(PY_FILES)

# 2) 所有纳管 .json 可解析（channels / kb/index / tests/golden / 工单模板）
gate-json:
	@echo "▶ gate-json: $(words $(JSON_FILES)) 个 .json"
	@for f in $(JSON_FILES); do \
	  $(PY) -c "import json,sys; json.load(open(sys.argv[1], encoding='utf-8'))" "$$f" \
	    || { echo "❌ 非法 JSON: $$f"; exit 1; }; \
	done

# 3) 项目级 agent 定义：必须有 frontmatter，且含 name / model / description
gate-agents:
	@echo "▶ gate-agents: $(words $(AGENT_MDS)) 个 agent"
	@for f in $(AGENT_MDS); do \
	  head -1 "$$f" | grep -q '^---$$' || { echo "❌ 缺 frontmatter: $$f"; exit 1; }; \
	  for key in name model description; do \
	    grep -q "^$$key:" "$$f" || { echo "❌ $$f 缺 frontmatter 字段: $$key"; exit 1; }; \
	  done; \
	done

# 4) 仓库卫生：不得纳管 .bak / .DS_Store / 数据面目录；不得出现明文密钥模式
gate-hygiene:
	@echo "▶ gate-hygiene"
	@! git ls-files | grep -E '\.bak(-|$$)|\.DS_Store$$|^\.bidmaster/|^\.bidboard/' \
	  || { echo "❌ 仓库内存在不应纳管的文件（.bak / .DS_Store / 数据面）"; exit 1; }
	@! git ls-files -z | xargs -0 grep -nIE "(api[_-]?key|secret|token|password)\s*[=:]\s*['\"][A-Za-z0-9_\-]{16,}['\"]" 2>/dev/null \
	  || { echo "❌ 疑似明文密钥，请改为环境变量"; exit 1; }

regress:
	@$(PY) rules/regress.py

install-hooks:
	@mkdir -p .git/hooks
	@cp rules/hooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
	@echo "✅ 已安装 .git/hooks/pre-commit → make gate"

install-capture:
	@echo "▶ install-capture: crawl4ai + playwright + openpyxl"
	@python3 -m venv .venv
	@. .venv/bin/activate && pip install -r requirements-capture.txt
	@. .venv/bin/activate && playwright install chromium
	@echo "✅ 标讯抓取依赖安装完成（.venv）"

selftest:
	@$(PY) rules/desensitize.py --selftest

gate-tests:
	@echo "▶ gate-tests: 门禁安全带（应拦必拦/应放必放）"
	@$(PY) tests/test_set_stage.py
	@$(PY) tests/test_store_readnow.py
	@$(PY) tests/test_digest_cloud.py

gate-api:
	@echo "▶ gate-api: HTTP API v1 契约测试（密封隔离）"
	@$(PY) tests/test_api.py

gate-truth:
	@echo "▶ gate-truth: 真相源一致性（登记制/副本漂移）"
	@$(PY) rules/reconcile.py --check

gate-skills:
	@echo "▶ gate-skills: agent 接入契约同步"
	@$(PY) rules/gate_skills.py
