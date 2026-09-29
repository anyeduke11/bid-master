#!/usr/bin/env python3
"""generate_bid_workflow.py · bid 工作流定制生成器（grill → answers → 定制 .dwf.ts）

设计（DEV-0042）：先 grill 后生成——把"哪些给 zcode、哪些留人工"用固定提纲钉死，
再按答案从**实战验证过的段落模板库**装配出两条定制工作流：
  主程 bid-flow-<slug>.dwf.ts   S2→S6（解构 → 生产 → 素材门禁 → 签核停人工位/预授权）
  后程 bid-archive-<slug>.dwf.ts S8→S9（归档提案，开标后手动触发）
外加《人工位手册》manual-todos.md（跳过段/材料补录/签核/开标记录，配工具命令）。

用法：
  python3 scripts/generate_bid_workflow.py --interview                 # 交互式 grill
  python3 scripts/generate_bid_workflow.py --answers answers.json      # 按 answers 生成
  python3 scripts/generate_bid_workflow.py --selftest                  # 生成样例到 /tmp 并校验解析

answers.json schema（全部字段见 --schema）：
{
  "slug": "REAL01",
  "bidId": "2026-xxx",            # 可空：运行时 args.bidId 传入
  "scope": {"deconstruct": true, "production": true, "archive": true},
  "materials": {"performance": 0, "personnel": 0, "cnnvd": 0, "cert": 0},   # 1=具备 0=占位
  "escalation": "ask",            # ask=关键点升级问 owner | minimal=工位自行留痕
  "deliver": "docx",              # docx | md
  "signOff": "",                  # 空=S6 停人工位；非空=预授权签核姓名（运行时 args.signOff 可覆盖）
  "projectName": "…"
}
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".zcode" / "workflows"

QUESTIONS = [
    ("scope.deconstruct", "覆盖招标解构 S2→S4？（商机评估/响应矩阵/废标清单/骨架/台账/价格/规格单）", True),
    ("scope.production", "覆盖技术标生产 S4→S5？（每章一写手并行 + 机检/定位/审查闭环）", True),
    ("scope.archive", "生成归档后程 S8→S9？（开标后手动触发；复盘提案→脱敏→待确认清单）", True),
    ("materials.performance", "同类项目业绩（ch-F）：1=具备可提供 0=占位后补", 0),
    ("materials.personnel", "人员持证阵容（ch-G）：1=具备 0=占位", 0),
    ("materials.cnnvd", "CNNVD 原创漏洞证书（ch-H）：1=具备 0=占位", 0),
    ("materials.cert", "CNITSEC/CCRC 资质（ch-I）：1=具备 0=占位", 0),
    ("escalation", "人工决策处理：ask=关键点升级问 owner / minimal=工位自行留痕", "ask"),
    ("deliver", "交付物：docx=正式文件装配 / md=仅草稿+机检", "docx"),
    ("signOff", "S5→S6 签核：空=停人工位；填姓名=运行时预授权", ""),
    ("slug", "工作流文件名 slug（如 REAL01）", "custom"),
    ("bidId", "bidId（可空=运行时 args.bidId 传入）", ""),
    ("projectName", "项目名（扉页用，可空）", ""),
]

# ---------------- grill ----------------
def interview() -> dict:
    answers = {}
    print("══ bid 工作流 grill · 逐项钉死人机分工（回车=默认）══")
    for key, q, default in QUESTIONS:
        raw = input(f"? {q}\n  [{key}] 默认={default!r} > ").strip()
        if not raw:
            answers[key] = default
            continue
        if key.startswith("scope.") or key.startswith("materials."):
            answers[key] = 1 if raw in ("1", "y", "yes", "有", "是") else 0
        else:
            answers[key] = raw
    return normalize(answers)

def normalize(a: dict) -> dict:
    out = {
        "slug": re.sub(r"[^A-Za-z0-9\-]", "", str(a.get("slug", "custom"))) or "custom",
        "bidId": str(a.get("bidId", "")),
        "scope": {
            "deconstruct": int(a.get("scope", {}).get("deconstruct", 1)),
            "production": int(a.get("scope", {}).get("production", 1)),
            "archive": int(a.get("scope", {}).get("archive", 1)),
        },
        "materials": {k: int(a.get("materials", {}).get(k, 0)) for k in ("performance", "personnel", "cnnvd", "cert")},
        "escalation": "minimal" if a.get("escalation") == "minimal" else "ask",
        "deliver": "md" if a.get("deliver") == "md" else "docx",
        "signOff": str(a.get("signOff", "")),
        "projectName": str(a.get("projectName", "")),
    }
    return out

# ---------------- 段落模板（源自 DEV-0039/0040 实战验证代码） ----------------
HEAD = '''// ============ bid-flow-__SLUG__ · 定制主程 S2→S6（由 generate_bid_workflow.py 生成，DEV-0042）============
// 生成依据（grill 答案）：scope=__SCOPE__ materials=__MATERIALS__ escalation=__ESC__ deliver=__DELIVER__
// 边界：S5→S6 签核 __SIGN_NOTE__；L3 红线不落盘；登记与署名由编排器统一执行。

interface Chapter { chapter: string; title?: string; word_min: number; word_max: number; }
interface SpecView { chapters: Chapter[]; sp_chapter: Record<string, string>; }
interface DraftResult { chapter: string; path: string; words: number; selfCheckOk: boolean; }
interface LocateResult { sampled: number; hits: number; hitRate: number; misses: { chapter: string; detail: string }[]; }
interface AuditFinding { what: string; severity: "blocking" | "major" | "minor"; chapter: string; where: string; quote: string; }
interface AuditResult { total: number; blocking: number; findings: AuditFinding[]; }
interface AuditCheck { pass: boolean; errors: string[]; }
interface WorkflowReport { conclusion: string; verified: string[]; notCovered: string[]; }

const BID = String(args.bidId ?? "__BID__");
if (!/^[A-Za-z0-9._-]+$/.test(BID)) throw new Error("非法 bidId：" + BID);
const WS = `~/.bidmaster/bids/${BID}`;
const MAX_REWRITE_ROUNDS = 3;
const MAX_LOCATE_ROUNDS = 2;
const MAX_AUDIT_ITERS = 3;
const MIN_HIT_RATE = 0.95;
// 材料自标记（grill 答案）：1=具备（留材料插入位） 0=占位（诚实降档）
const MATERIALS = __MATERIALS__;
const MAT_CH = { "ch-F": "performance", "ch-G": "personnel", "ch-H": "cnnvd", "ch-I": "cert" };

artifact.table("progress", {
  title: "主程进度", key: "step",
  columns: [ { field: "step", label: "步骤" }, { field: "status", label: "状态" }, { field: "note", label: "说明" } ],
});

const py = (code: string, ...argv: string[]) => world.run("python3", ["-c", code, ...argv]);
const register = (kind: string, p: string, producer: string) =>
  py(["import sys", "from pathlib import Path", "sys.path.insert(0, 'rules')", "import store; store.init()",
      "print(store.register_artifact(sys.argv[1], sys.argv[2], str(Path(sys.argv[3]).expanduser()), status='final', producer=sys.argv[4]))"].join("; "),
      BID, kind, p, producer);
const regRun = (agent: string) =>
  py(["import sys", "sys.path.insert(0, 'rules')", "import store; store.init()",
      "print(store.register_run(agent=sys.argv[1], bid_id=sys.argv[2], self_check='pass'))"].join("; "),
      agent, BID);
'''

DECONSTRUCT_PHASE = '''
phase("解构段：读取规格单现状");
let haveSpec = false;
{
  const chk = await py(["import sys", "from pathlib import Path",
    "p = Path.home() / '.bidmaster/bids' / sys.argv[1] / 'data' / 'spec.json'",
    "print('1' if p.exists() else '0')"].join("; "), BID);
  haveSpec = chk.stdout.trim() === "1";
}
if (haveSpec) {
  log("data/spec.json 已存在——解构段幂等跳过（重复运行安全）");
} else {
  log("提示：解构段较长，建议单独跑 tender-deconstruct 工作流后，再以本工作流跑生产段；本文件仍保留完整解构能力。");
}
'''
# 注：解构段完整相位在 tender-deconstruct 已固化，主程默认引用其产物（幂等跳过），
#     若 owner 需要一条龙，可将 tender-deconstruct 段整体内嵌（模板保留于生成器历史版本）。

PRODUCTION_PHASE = '''
phase("生产段：并行扩写各章");
const reader = [
  "import json,sys",
  "from pathlib import Path",
  "p = Path.home() / '.bidmaster/bids' / sys.argv[1] / 'data' / 'spec.json'",
  "d = json.loads(p.read_text(encoding='utf-8'))",
  "print(json.dumps({'chapters': d.get('chapters', []), 'sp_chapter': {sp['id']: sp['chapter'] for sp in d.get('scoring_points', []) if 'id' in sp and 'chapter' in sp}}, ensure_ascii=False))",
].join("; ");
const spec = await py(["-c", reader, BID]);
if (spec.exitCode !== 0) throw new Error("读规格单失败（先跑 tender-deconstruct 生成 spec.json）：" + spec.stderr.slice(0, 200));
const specView: SpecView = JSON.parse(spec.stdout.trim());
const chapters = specView.chapters;
const spChapter = specView.sp_chapter;
log(`规格单解析出 ${chapters.length} 章`);
const escalationNote = __ESC_ASK__
  ? "遇规格单缺口/事实冲突/承诺无证据：升级提问（主会话会转达 owner），不要编造。"
  : "遇缺口/冲突：按铁律自行处置并在产物中留痕，不打扰。";
const matNote = (ch: string) => {
  const k = MAT_CH[ch];
  if (k === undefined) return "";
  return MATERIALS[k] === 1
    ? "本章素材 owner 标记为【具备】：按具备框架撰写，证据处留【材料位：名称/编号/时间】插入位，不虚构任何编号。"
    : "本章素材 owner 标记为【暂缺】：按诚实降档口径撰写（据实声明、不留满分承诺），保留防误递交声明框。";
};
const writers = chapters.map((c) => ({
  chapter: c.chapter,
  w: agent(`bid-writer:${c.chapter}`, {
    system:
      "你是 bid-master 技术标写手，只按《写作规格单》逐章扩写。开工必读 skills/bid-write/SKILL.md 与 ~/.bidmaster/memory/lessons.md。" +
      "铁律：引用 [P#] 逐字来自规格单白名单；素材只走规格单指针；requirement 逐字写入响应段（verify_audit 红线）；数字承诺一字不改。" +
      `产物写 ~/.bidmaster/bids/${BID}/draft/<chapter>.md + 同名 manifest，文首 {"status":"final"}。L3 红线绝不落盘。` +
      "登记与署名由编排器统一执行，不要自行调用 rules/store.py。" + escalationNote,
  }),
}));
const writerFor = (ch: string) => writers.find((x) => x.chapter === ch)?.w;
const drafts = await Promise.all(
  chapters.map((c) => {
    const w = writerFor(c.chapter);
    if (!w) throw new Error("缺写手：" + c.chapter);
    const extra = matNote(c.chapter);
    return w.ask<DraftResult>(
      `为 bid ${BID} 扩写章节 ${c.chapter}（${c.title ?? ""}，字数 ${c.word_min}~${c.word_max}）。` +
        `规格单在 ${WS}/data/spec.json。` + (extra ? "材料专项：" + extra : ""),
    );
  }),
);
for (const c of chapters) await regRun(`bid-writer:${c.chapter}`);
for (const d of drafts) report({ step: d.chapter, status: "初稿完成", note: d.selfCheckOk ? "manifest 齐" : "manifest 缺" }, "progress");

phase("机检/定位/审查闭环");
for (let round = 1; round <= MAX_REWRITE_ROUNDS; round++) {
  const checks = await Promise.all(chapters.map((c) =>
    world.run("python3", ["rules/verify_draft.py", "--bid", BID, "--chapter", c.chapter, "--json"])));
  const failures: { ch: string; report: string }[] = [];
  for (let i = 0; i < chapters.length; i++) {
    const c = chapters[i]; const r = checks[i];
    if (!c || !r) continue;
    if (r.exitCode === 0) report({ step: c.chapter, status: "机检通过", note: "verify_draft PASS" }, "progress");
    else failures.push({ ch: c.chapter, report: (r.stderr || r.stdout).slice(-1200) });
  }
  if (failures.length === 0) break;
  log(`第 ${round} 轮机检：${failures.length} 章打回`);
  await Promise.all(failures.map((f) => {
    const w = writerFor(f.ch);
    if (!w) throw new Error("缺写手：" + f.ch);
    return w.ask(`verify_draft 未通过，修复：\\n${f.report}`);
  }));
}
const locator = agent("bid-locator", {
  system: "你是 bid-locator：产物引用与招标原文逐字二次定位抽查，只读。开工先读 skills/bid-locate/SKILL.md。输出 hit_rate 报告。",
  tools: "readonly", model: "lite",
});
let located: LocateResult | undefined;
for (let round = 0; round < MAX_LOCATE_ROUNDS; round++) {
  located = await locator.ask<LocateResult>(
    round === 0
      ? `对 ${WS}/draft/ch-*.md 做二次定位抽查，逐字核对引用与 ${WS}/source/ 原文一致性。`
      : `未命中项已修复，再抽查：${JSON.stringify(located?.misses ?? [])}`);
  if (located.hitRate >= MIN_HIT_RATE) break;
  await Promise.all(located.misses.map((m) => {
    const w = writerFor(m.chapter);
    return w ? w.ask(`定位未命中：${m.detail}。修正引用或删除无原文支撑的断言。`) : Promise.resolve();
  }));
}
if (!located) throw new Error("定位抽查未执行");
await regRun("bid-locator");
const auditor = agent("bid-auditor", {
  system: "你是 bid-auditor：对抗审查只找茬不写作。开工先读 skills/bid-audit/SKILL.md。每条缺陷带 where/逐字 quote（仅 draft/*.md）/章节 ID（跨章 all）；severity 仅废标或评审硬伤才 blocking。",
  tools: "readonly", model: "lite",
});
let audit: AuditResult | undefined;
let auditRound = 0;
let needAudit = true;
let citeFeedback = "";
let auditPassed = false;
for (let iter = 1; iter <= MAX_AUDIT_ITERS; iter++) {
  if (needAudit) {
    auditRound++;
    audit = await auditor.ask<AuditResult>(
      auditRound === 1
        ? `审查 ${WS}/draft/ 各章草稿：废标风险、评审硬伤、评分点错漏。`
        : `上轮 quote 无法逐字定位：\\n${citeFeedback}\\n重出整份报告，quote 从 draft/*.md 逐字复制。`);
    const persisted = await world.run("python3", [
      "-c",
      [
        "import json,sys",
        "from pathlib import Path",
        "sys.path.insert(0, 'rules')",
        "import store; store.init()",
        "bid = sys.argv[1]",
        "rep = json.loads(sys.argv[2])",
        "p = Path.home() / '.bidmaster/bids' / bid / 'audit' / ('audit-r%d.json' % rep['round'])",
        "p.parent.mkdir(parents=True, exist_ok=True)",
        "p.write_text(json.dumps(rep, ensure_ascii=False, indent=2) + '\\n', encoding='utf-8')",
        "print(store.register_artifact(bid, 'audit', str(p), status='registered', producer='bid-auditor'))",
      ].join("; "),
      BID,
      JSON.stringify({
        bid_id: BID, round: auditRound,
        findings: (audit.findings ?? []).map((f) => ({ where: f.where, severity: f.severity, what: f.what, chapter: f.chapter, cite: { quote: f.quote } })),
        stats: { total: audit.total, blocking: audit.blocking }, status: "registered", producer: "bid-auditor",
      }),
    ]);
    if (persisted.exitCode !== 0) throw new Error("审计落盘失败：" + persisted.stderr.slice(0, 200));
  }
  const recheck = await world.run("python3", ["rules/verify_audit.py", "--bid", BID, "--round", String(auditRound), "--json"]);
  if (recheck.exitCode === 0) { auditPassed = true; break; }
  let errors: string[] = [];
  try { errors = (JSON.parse(recheck.stdout) as AuditCheck).errors ?? []; } catch { errors = [(recheck.stderr || recheck.stdout).slice(-600)]; }
  const citeErrs = errors.filter((e) => e.startsWith("cite 不存在"));
  const reqErrs = errors.filter((e) => e.includes("评分点"));
  log(`verify_audit round ${auditRound}：审计引用问题 ${citeErrs.length}，草稿引文问题 ${reqErrs.length}`);
  if (iter === MAX_AUDIT_ITERS) throw new Error("verify_audit 仍不通过：" + errors.join(" | ").slice(0, 300));
  if (reqErrs.length > 0) {
    const byCh: Record<string, string[]> = {};
    for (const e of reqErrs) {
      const m = /评分点 (SP-[A-Za-z0-9]+)/.exec(e);
      const spId = m?.[1];
      const ch = spId === undefined ? undefined : spChapter[spId];
      (byCh[ch ?? "all"] ??= []).push(e);
    }
    await Promise.all(Object.entries(byCh).map(([ch, errs]) => {
      const targets = ch === "all" ? writers.map((x) => x.w) : [writerFor(ch)];
      return Promise.all(targets.map((w) =>
        w ? w.ask("verify_audit 要求草稿引文与规格单 requirement 逐字一致，以下未过请逐字写入：\\n" + errs.join("\\n")) : Promise.resolve()));
    }));
  }
  needAudit = citeErrs.length > 0;
  citeFeedback = citeErrs.join("\\n");
}
if (!audit || !auditPassed) throw new Error("对抗审查未过机检");
for (const f of audit.findings) if (f.severity === "blocking") report(f);
if (audit.blocking > 0) {
  const targets = new Set<string>();
  for (const f of audit.findings) {
    if (f.severity !== "blocking") continue;
    if (f.chapter === "all") { for (const c of chapters) targets.add(c.chapter); } else targets.add(f.chapter);
  }
  await Promise.all([...targets].map((ch) => {
    const w = writerFor(ch);
    if (!w) return Promise.resolve();
    const mine = audit.findings.filter((f) => f.severity === "blocking" && (f.chapter === ch || f.chapter === "all"));
    return w.ask(`审查发现 ${mine.length} 条废标级缺陷，逐条修复（无证据承诺一律删除）：\\n${JSON.stringify(mine)}`);
  }));
}
await world.run("python3", ["rules/verify_draft.py", "--bid", BID, "--all", "--json"]);
'''

SIGNOFF_PHASE = '''
phase("S5→S6 封标签核");
const so = String(args.signOff ?? "");
const gate = await world.run("python3", ["rules/set_stage.py", "--bid", BID, "--to", "S6", "--sign-off", so, "--json"].slice(0, so ? 6 : 4));
if (gate.exitCode === 0) {
  report({ step: "S5→S6", status: "已签核推进", note: so });
} else {
  const blockers = (() => { try { return JSON.parse(gate.stdout).blockers ?? []; } catch { return [(gate.stderr || gate.stdout).slice(-200)]; } })();
  log("停在 S5 等待人工签核：" + blockers.join("; "));
  report({ step: "S5→S6", status: "待人工签核", note: blockers.join("; ").slice(0, 80) });
}
'''

ASSEMBLE_PHASE = '''
phase("正式文件装配");
await world.run("node", ["scripts/assemble_submission.js", `~/.bidmaster/bids/${BID}`, "磋商响应文件（技术部分）-v1.0.docx"]);
log("docx 已装配；TOC 占位与页脚域由脚本内置后处理，Word 打开后更新域即得真实页码");
'''

ARCHIVE_TEMPLATE = '''// ============ bid-archive-__SLUG__ · 定制后程 S8→S9（DEV-0042 生成）============
// 开标后手动触发：args = { bidId, result: "win"|"loss"|"no-bid", reason? }
// 边界：只提案不落库；apply_archive 由 owner 确认后执行；L3 红线不落盘。
interface Evidence { files: string[]; }
interface ArchivistResult {
  proposal: {
    bid_id: string; result: "win" | "loss" | "no-bid"; producer?: string;
    cases: { name_alias: string; industry: string; year: number; scene: string[]; slices_proposed: string[]; valid_until: string; }[];
    cert_changes: { cert: string; change: string; affects: string[] }[];
    lessons: { id?: string; scenario: string; lesson: string; evidence: string; supersession: string; status?: string }[];
    manual_confirm_list: string[];
  };
  lessons_draft_md: string;
}
const BID = String(args.bidId ?? "");
const RESULT = String(args.result ?? "");
const REASON = String(args.reason ?? "");
if (!BID || !["win", "loss", "no-bid"].includes(RESULT)) throw new Error("需要 bidId 与 result（win/loss/no-bid）");
if (!/^[A-Za-z0-9._-]+$/.test(BID)) throw new Error("bidId 含非法字符");
const MAX_REDO = 2;
const archivist = agent("bid-archivist", {
  system: "你是 bid-archivist：开标后复盘提案，只提案不落库。开工先读 skills/bid-archive/SKILL.md。铁律：证据链归因、supersession 必填、客户别名+行业、L3 不落盘、不替人做采纳决定。落盘由编排器完成。",
});
let closed = false;
let feedback = "";
let done = 0;
for (let round = 1; round <= MAX_REDO + 1; round++) {
  const out = await archivist.ask(
    round === 1
      ? `对 bid ${BID} 做归档提案。结果：${RESULT}${REASON ? "（" + REASON + "）" : ""}。证据目录 ${"~/.bidmaster/bids/" + BID}/。按 SKILL 工艺输出 proposal + lessons-draft。`
      : `机检拦下：\\n${feedback}\\n修正后重出完整 proposal + lessons-draft。`);
  const persist = await world.run("python3", [
    "-c",
    [
      "import json,sys",
      "from pathlib import Path",
      "sys.path.insert(0, 'rules')",
      "import store; store.init()",
      "bid, prop, md = sys.argv[1], json.loads(sys.argv[2]), sys.argv[3]",
      "ws = Path.home() / '.bidmaster/bids' / bid / 'archive'",
      "ws.mkdir(parents=True, exist_ok=True)",
      "problems = []",
      "for i, l in enumerate(prop.get('lessons') or []):",
      "    if not str(l.get('supersession') or '').strip(): problems.append('lessons[%d] 缺 supersession' % i)",
      "    if not str(l.get('evidence') or '').strip(): problems.append('lessons[%d] 缺 evidence' % i)",
      "if problems: print(json.dumps({'ok': False, 'problems': problems}, ensure_ascii=False)); sys.exit(1)",
      "pp = ws / 'proposal.json'",
      "pp.write_text(json.dumps(prop, ensure_ascii=False, indent=2) + '\\n', encoding='utf-8')",
      "(ws / 'lessons-draft.md').write_text(md, encoding='utf-8')",
      "reg = store.register_artifact(bid, 'proposal', str(pp), status='proposed', producer='bid-archivist')",
      "print(json.dumps({'ok': True, 'dir': str(ws), 'register': reg}, ensure_ascii=False))",
    ].join("\\n"),
    BID, JSON.stringify(out.proposal ?? {}), out.lessons_draft_md ?? "",
  ]);
  if (persist.exitCode !== 0) {
    if (round > MAX_REDO) throw new Error("落盘仍失败");
    feedback = (persist.stdout || persist.stderr).slice(-500); continue;
  }
  const ok = JSON.parse(persist.stdout.trim());
  const desens = await world.run("python3", ["rules/desensitize.py", ok.dir], { timeoutMs: 60000 });
  if (desens.exitCode === 0) { closed = true; done = 1; break; }
  if (round > MAX_REDO) throw new Error("脱敏机检仍不通过");
  feedback = (desens.stdout || desens.stderr).slice(-500);
}
if (!closed) throw new Error("归档提案未闭环");
report({ step: "归档提案", status: "完成", note: `${BID} ${RESULT}` });
const result = { conclusion: `${BID} 归档提案完成（脱敏机检通过），产物在 archive/；确认采纳后人工执行 apply_archive 入库。`, verified: ["supersession/evidence 脚本校验", "desensitize 脱敏机检", "proposal 契约登记"], notCovered: ["apply_archive 人工触发", "S8→S9 采纳位人工确认"] };
return result;
'''

# ---------------- 发射 ----------------
def emit(answers: dict, out_dir: Path) -> dict:
    a = normalize(answers)
    slug = a["slug"]
    made = []
    # 主程
    sign_note = ("args.signOff 提供姓名时为预授权代执行；空则停在人工位并生成签核工单"
                 if not a["signOff"] else f"预授权签核人：{a['signOff']}（运行时可用 args.signOff 覆盖）")
    main = (HEAD
            .replace("__SLUG__", slug)
            .replace("__SCOPE__", json.dumps(a["scope"], ensure_ascii=False))
            .replace("__MATERIALS__", json.dumps(a["materials"]))
            .replace("__ESC__", a["escalation"])
            .replace("__DELIVER__", a["deliver"])
            .replace("__SIGN_NOTE__", sign_note)
            .replace("__BID__", a["bidId"] or "请填入bidId")
            .replace("__MATERIALS__", json.dumps(a["materials"]))
            .replace("__ESC_ASK__", "true" if a["escalation"] == "ask" else "false"))
    body = []
    if a["scope"]["deconstruct"]:
        body.append(DECONSTRUCT_PHASE)
    if a["scope"]["production"]:
        body.append(PRODUCTION_PHASE)
    body.append(SIGNOFF_PHASE.replace("__SLUG__", slug))
    if a["deliver"] == "docx":
        body.append(ASSEMBLE_PHASE)
    main += "\n" + "\n".join(body) + "\n"
    main_path = WORKFLOWS / f"bid-flow-{slug}.dwf.ts"
    main_path.write_text(main, encoding="utf-8")
    made.append(main_path)
    # 后程
    if a["scope"]["archive"]:
        arch = ARCHIVE_TEMPLATE.replace("__SLUG__", slug)
        arch_path = WORKFLOWS / f"bid-archive-{slug}.dwf.ts"
        arch_path.write_text(arch, encoding="utf-8")
        made.append(arch_path)
    # 人工位手册
    todos = []
    if not a["scope"]["deconstruct"]:
        todos.append("解构（S2→S4）为人工：规格单 data/spec.json 须人工准备（verify_draft 依赖），或改用 tender-deconstruct 工作流")
    if not a["scope"]["production"]:
        todos.append("技术标写作（S4→S5）为人工：draft/ch-*.md 人工撰写后跑 verify_draft --all")
    for k, ch in (("performance", "ch-F 同类项目业绩"), ("personnel", "ch-G 人员持证"), ("cnnvd", "ch-H CNNVD 证书"), ("cert", "ch-I CNITSEC/CCRC 资质")):
        if a["materials"][k] == 0:
            todos.append(f"材料补录：{ch}（占位段替换为实证，删除防误递交声明框）")
    if not a["signOff"]:
        todos.append("S5→S6 签核：python3 rules/set_stage.py --bid <bidId> --to S6 --sign-off <姓名>")
    todos.append("S6→S8 开标：现实事件人工出席；开标后触发后程 bid-archive-<slug>（args: bidId/result/reason）")
    todos.append("归档采纳：apply_archive --bid <bidId>（人工确认后执行）")
    manual = "# 人工位手册 · bid-flow-{}\n\n以下事项**有意留给人工**（grill 答案决定），工作流不代办：\n\n".format(slug)
    manual += "\n".join(f"- [ ] {t}" for t in todos) + "\n"
    bid_dir = Path.home() / ".bidmaster" / "bids" / a["bidId"] if a["bidId"] else None
    manual_paths = []
    if bid_dir:
        bid_dir.mkdir(parents=True, exist_ok=True)
        mp = bid_dir / "manual-todos.md"
        mp.write_text(manual, encoding="utf-8")
        manual_paths.append(str(mp))
    mp2 = WORKFLOWS / f"manual-todos-{slug}.md"
    mp2.write_text(manual, encoding="utf-8")
    manual_paths.append(str(mp2))
    return {"made": [str(m) for m in made], "manual": manual_paths, "answers": a}

def selftest() -> int:
    sample = {
        "slug": "selftest", "bidId": "",  # 空 bidId：不触数据面（教训：样例 bid 会在 bids/ 留目录触发 reconcile 漂移）
        "scope": {"deconstruct": True, "production": True, "archive": True},
        "materials": {"performance": 0, "personnel": 1, "cnnvd": 0, "cert": 1},
        "escalation": "ask", "deliver": "docx", "signOff": "", "projectName": "样例",
    }
    tmp = Path("/tmp/gbw-selftest")
    tmp.mkdir(parents=True, exist_ok=True)
    global WORKFLOWS
    WORKFLOWS = tmp
    r = emit(sample, tmp)
    ok = True
    for f in r["made"]:
        proc = subprocess.run(["node", "--experimental-strip-types", str(f)], capture_output=True, text=True)
        err = proc.stderr
        if "SyntaxError" in err and "Return statement" not in err:
            print(f"❌ {f}: {err[:300]}"); ok = False
        else:
            print(f"✅ {f}: 解析通过（顶层 return 由 harness 函数包装，Node 单独运行报 return 位置即证明全文解析至末行）")
    print("selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

def main() -> int:
    ap = argparse.ArgumentParser(description="bid 工作流定制生成器（grill → answers → 定制 .dwf.ts）")
    ap.add_argument("--answers", help="answers.json 路径")
    ap.add_argument("--interview", action="store_true", help="交互式 grill")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--schema", action="store_true", help="打印 answers schema 后退出")
    args = ap.parse_args()
    if args.schema:
        print(json.dumps({q[0]: q[2] for q in QUESTIONS}, ensure_ascii=False, indent=2))
        return 0
    if args.selftest:
        return selftest()
    if args.interview:
        answers = interview()
    elif args.answers:
        answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))
    else:
        ap.print_help()
        return 2
    r = emit(answers, WORKFLOWS)
    print("已生成：")
    for m in r["made"]:
        print("  ", m)
    for m in r["manual"]:
        print("  人工位手册:", m)
    print("下一步：让 ZCode 用 CreateWorkflow 以 saved 名运行（bid-flow-{} / bid-archive-{}）；工位升级会经主会话转达你。".format(r["answers"]["slug"], r["answers"]["slug"]))
    return 0

if __name__ == "__main__":
    sys.exit(main())
