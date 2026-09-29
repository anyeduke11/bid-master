#!/usr/bin/env python3
"""gate_skills.py · agent 接入契约同步检查（P1-5 · make gate 挂载）

校验三处一致（任一漂移即红）：
  1. contracts/agents/*.json ↔ .zcode/agents/<name>.md frontmatter（name/model 一致）
  2. 每个 agent 契约的 produces kind ⊆ contracts/artifact/ 已定义契约
  3. 只读 agent（readonly=true）的 tools 不得包含写类工具（Write/Edit）
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CA = REPO / "contracts" / "agents"
ZA = REPO / ".zcode" / "agents"
WRITE_TOOLS = {"Write", "Edit", "Bash"}
READONLY_SAFE = {"Read", "Glob", "Grep"}
# markdown 类产物（无法 JSON schema 化）白名单：由 verify_draft/verify_audit 流程机检兜底
NO_CONTRACT_OK = {"draft"}


def fm_of(md: Path) -> dict:
    text = md.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    fm = {}
    for ln in m.group(1).splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            fm[k.strip()] = v.strip().strip('"')
    return fm


def check() -> list:
    problems = []
    if not CA.exists():
        return ["缺 contracts/agents/ 目录"]
    contract_names = set()
    for cj in sorted(CA.glob("*.json")):
        d = json.loads(cj.read_text(encoding="utf-8"))
        name = d.get("name")
        if not name:
            problems.append(f"{cj.name} 缺 name")
            continue
        contract_names.add(name)
        md_flag = d.get("md", True)
        md = ZA / f"{name}.md"
        if md_flag and not md.exists():
            problems.append(f"契约 {name} 无对应 .zcode/agents/{name}.md")
            continue
        if not md_flag:
            continue   # 会话型主 Agent：无 agent 文件，工艺在 skills/bid-master/
        fm = fm_of(md)
        if fm.get("model", "") != d.get("model", ""):
            problems.append(f"{name}: model 漂移（契约={d.get('model')!r} vs md={fm.get('model')!r}）")
        tools = set()
        raw = md.read_text(encoding="utf-8")
        m = re.search(r"^tools:\s*(.+)$", raw, re.M)
        if m:
            tools |= {t.strip() for t in m.group(1).split(",")}
        m2 = re.search(r"^tools:\n((?:\s+- .+\n)+)", raw, re.M)
        if m2:
            tools |= {ln.strip()[2:] for ln in m2.group(1).splitlines()}
        if d.get("readonly") and tools & WRITE_TOOLS:
            problems.append(f"{name}: 只读契约但 md 声明了写类工具 {sorted(tools & WRITE_TOOLS)}")
        for k in d.get("produces", []):
            if k in NO_CONTRACT_OK:
                continue
            if not (REPO / "contracts" / "artifact" / f"{k}.schema.json").exists():
                problems.append(f"{name} produces 未契约化：{k}")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("⛔ agent 契约同步漂移：")
        for p in problems:
            print("  -", p)
        return 1
    n = len(list(CA.glob("*.json"))) if CA.exists() else 0
    print(f"✅ gate-skills：{n} 个 agent 接入契约一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
