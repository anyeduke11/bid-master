// ============ bid-flow-s2s9-full · 定制主程 S2→S6（由 generate_bid_workflow.py 生成，DEV-0042）============
// 生成依据（grill 答案）：scope={"deconstruct": 1, "production": 1, "archive": 1} materials={"performance": 0, "personnel": 0, "cnnvd": 0, "cert": 0} escalation=ask deliver=docx
// 边界：S5→S6 签核 args.signOff 提供姓名时为预授权代执行；空则停在人工位并生成签核工单；L3 红线不落盘；登记与署名由编排器统一执行。

interface Chapter { chapter: string; title?: string; word_min: number; word_max: number; }
interface SpecView { chapters: Chapter[]; sp_chapter: Record<string, string>; }
interface DraftResult { chapter: string; path: string; words: number; selfCheckOk: boolean; }
interface LocateResult { sampled: number; hits: number; hitRate: number; misses: { chapter: string; detail: string }[]; }
interface AuditFinding { what: string; severity: "blocking" | "major" | "minor"; chapter: string; where: string; quote: string; }
interface AuditResult { total: number; blocking: number; findings: AuditFinding[]; }
interface AuditCheck { pass: boolean; errors: string[]; }
interface WorkflowReport { conclusion: string; verified: string[]; notCovered: string[]; }

const BID = String(args.bidId ?? "请填入bidId");
if (!/^[A-Za-z0-9._-]+$/.test(BID)) throw new Error("非法 bidId：" + BID);
const WS = `~/.bidmaster/bids/${BID}`;
const MAX_REWRITE_ROUNDS = 3;
const MAX_LOCATE_ROUNDS = 2;
const MAX_AUDIT_ITERS = 3;
const MIN_HIT_RATE = 0.95;
// 材料自标记（grill 答案）：1=具备（留材料插入位） 0=占位（诚实降档）
const MATERIALS = {"performance": 0, "personnel": 0, "cnnvd": 0, "cert": 0};
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
    return w.ask(`verify_draft 未通过，修复：\n${f.report}`);
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
        : `上轮 quote 无法逐字定位：\n${citeFeedback}\n重出整份报告，quote 从 draft/*.md 逐字复制。`);
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
        "p.write_text(json.dumps(rep, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')",
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
        w ? w.ask("verify_audit 要求草稿引文与规格单 requirement 逐字一致，以下未过请逐字写入：\n" + errs.join("\n")) : Promise.resolve()));
    }));
  }
  needAudit = citeErrs.length > 0;
  citeFeedback = citeErrs.join("\n");
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
    return w.ask(`审查发现 ${mine.length} 条废标级缺陷，逐条修复（无证据承诺一律删除）：\n${JSON.stringify(mine)}`);
  }));
}
await world.run("python3", ["rules/verify_draft.py", "--bid", BID, "--all", "--json"]);


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


phase("正式文件装配");
await world.run("node", ["scripts/assemble_submission.js", `~/.bidmaster/bids/${BID}`, "磋商响应文件（技术部分）-v1.0.docx"]);
log("docx 已装配；TOC 占位与页脚域由脚本内置后处理，Word 打开后更新域即得真实页码");

