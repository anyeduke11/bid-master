/* zcode-workflow
description: bid-master 技术标生产流水线 v3.1：并行扩写→机检打回→定位抽查→对抗审查（审计落盘登记；verify_audit
  错误按类路由）→终检登记交付；v3.1 修复 bidId 拼入 python -c 代码串的注入面（改 argv 传参+格式白名单）
args:
  bidId:
    type: string
    description: "bid\r\r ID\r\r（如\r\r
      2026\r\r-GOLD\r\r-jishu\r\r-wftest\r\r）\r\r，其\r\r
      \r\r~\r\r/\r\r.bidmaster\r\r/bids\r\r/\r\r<bidId\r\r>\r\r/data\r\r/spec\r\
      \r.json\r\r 必须已就绪"
    required: true
  maxRewriteRounds:
    type: number
    description: 机检打回重写的最大轮数
    required: false
    default: 3
  minHitRate:
    type: number
    description: "定位抽查命中率门限\r\r（对应\r\r gates\r\r S5→S6\r\r 的\r\r locator\r\r_rate\r\r）"
    required: false
    default: 0.95
*/
// ============ bid-master 技术标生产流水线 v3.1（S4→S5 段）============
// 关联契约：contracts/workflows/tech-proposal-pipeline.json（actor ↔ agent ↔ skill ↔ gate 映射）
// 前提：该 bid 当前无其他会话占用（AGENTS.md 纪律 5）；~/.bidmaster/bids/<bidId>/data/spec.json 已就绪
// 边界：S5→S6 人工签核（set_stage.py --sign-off）与状态推进不由本流水线代办
// 安全：bidId 只经 argv 传给 python（不拼进 -c 代码串），并有格式白名单

interface Chapter {
  /** 章节 ID，如 ch-A */
  chapter: string;
  title?: string;
  word_min: number;
  word_max: number;
}
interface SpecView {
  chapters: Chapter[];
  /** 评分点 ID → 所属章节 */
  sp_chapter: Record<string, string>;
}
interface DraftResult {
  /** 章节 ID */
  chapter: string;
  /** 草稿落盘路径 */
  path: string;
  /** 正文字数 */
  words: number;
  /** manifest 齐全且 status=final */
  selfCheckOk: boolean;
}
interface LocateResult {
  /** 抽查条数 */
  sampled: number;
  /** 逐字命中条数 */
  hits: number;
  /** 命中率 0~1 */
  hitRate: number;
  /** 未命中清单 */
  misses: { chapter: string; detail: string }[];
}
interface AuditFinding {
  /** 缺陷一句话 */
  what: string;
  /** blocking = 废标级，S5→S6 要求为 0 */
  severity: "blocking" | "major" | "minor";
  /** 涉及章节 ID；跨章问题填 all */
  chapter: string;
  /** 被审文件路径 */
  where: string;
  /** 从 draft/*.md 正文逐字复制的摘录；非草稿文件的问题留空字符串 */
  quote: string;
}
interface AuditResult {
  total: number;
  blocking: number;
  findings: AuditFinding[];
}
interface AuditCheck {
  pass: boolean;
  errors: string[];
}
interface WorkflowReport {
  conclusion: string;
  findings: AuditFinding[];
  verified: string[];
  notCovered: string[];
}

const REPO = "/Users/duke/bid-master";
const BID = String(args.bidId ?? "");
if (!BID) throw new Error("缺少必填参数 bidId");
if (!/^[A-Za-z0-9._-]+$/.test(BID)) throw new Error(`bidId 含非法字符（仅允许字母/数字/./_/-）：${BID}`);
const MAX_REWRITE_ROUNDS = Number(args.maxRewriteRounds ?? 3);
const MAX_LOCATE_ROUNDS = 2;
const MAX_AUDIT_ITERS = 3;
const MIN_HIT_RATE = Number(args.minHitRate ?? 0.95);

artifact.table("progress", {
  title: "章节生产进度",
  key: "chapter",
  columns: [
    { field: "chapter", label: "章节" },
    { field: "status", label: "状态" },
    { field: "note", label: "说明" },
  ],
});

phase("读取规格单，拆出章节清单");
const reader = [
  "import json,sys",
  "from pathlib import Path",
  "p = Path.home() / '.bidmaster/bids' / sys.argv[1] / 'data' / 'spec.json'",
  "d = json.loads(p.read_text(encoding='utf-8'))",
  "print(json.dumps({'chapters': d.get('chapters', []), 'sp_chapter': {sp['id']: sp['chapter'] for sp in d.get('scoring_points', []) if 'id' in sp and 'chapter' in sp}}, ensure_ascii=False))",
].join("; ");
const spec = await world.run("python3", ["-c", reader, BID]);
if (spec.exitCode !== 0) throw new Error(`读规格单失败：${spec.stderr.slice(0, 300)}`);
const specView: SpecView = JSON.parse(spec.stdout.trim());
const chapters = specView.chapters;
const spChapter = specView.sp_chapter;
log(`规格单解析出 ${chapters.length} 章：${chapters.map((c) => c.chapter).join("、")}`);

// 写手每章一个、全程复用（persona 对齐 .zcode/agents/bid-writer.md 的铁律）
const writers = chapters.map((c) => ({
  chapter: c.chapter,
  w: agent(`bid-writer:${c.chapter}`, {
    system:
      "你是 bid-master 技术标写手，只按《写作规格单》逐章扩写，是流水线的扩写工位不是作者。" +
      "开工绑定：先完整读 /Users/duke/bid-master/skills/bid-write/SKILL.md，读不到就回复「SKILL.md 缺失」停止，禁止凭想象开工。" +
      "铁律：输出中每个招标文件引用 [P#] 必须逐字来自规格单白名单，禁止新增任何招标文件断言/页码/数据；" +
      "素材只走规格单给定的 kb 指针，禁止联网；规格单中的原文引用、数字、承诺值一字不改。" +
      `产物写入 ~/.bidmaster/bids/${BID}/draft/<chapter>.md：章节正文 + 同名 manifest（producer/model/输入指纹/ticket_id/自检结果），文首带 {"status":"final"}。` +
      "L3 红线（成本价/折扣/客户名单/证件号/证书编号）绝不落盘。" +
      "产物登记与署名由流水线编排器统一执行，不要自行调用 rules/store.py 的 register_artifact/register_run。" +
      "做不到的要求如实说明，不要编造。",
  }),
}));
const writerFor = (ch: string) => writers.find((x) => x.chapter === ch)?.w;

phase("并行扩写各章初稿");
const drafts = await Promise.all(
  chapters.map((c) => {
    const w = writerFor(c.chapter);
    if (!w) throw new Error(`章节 ${c.chapter} 没有对应写手`);
    return w.ask<DraftResult>(
      `为 bid ${BID} 扩写章节 ${c.chapter}（${c.title ?? ""}，字数 ${c.word_min}~${c.word_max}）。` +
        `规格单在 ~/.bidmaster/bids/${BID}/data/spec.json，评分点与引用白名单以它为准。` +
        `该章每个评分点的响应段开头必须逐字引用规格单 requirement 原文（verify_audit 机检逐字一致，改写即打回）；` +
        `素材用规格单 material_ptrs 指针与响应矩阵/应答骨架（~/.bidmaster/bids/${BID}/ 下 data/response_matrix.json、stage1_技术标应答骨架.md），禁止引入指针外素材。`,
    );
  }),
);
for (const d of drafts) {
  report(
    { chapter: d.chapter, status: "初稿完成", note: d.selfCheckOk ? "manifest 齐" : "manifest 缺，待机检确认" },
    "progress",
  );
}
// DEV-0041 遥测：工位 run 由编排器强制登记（run 计数入看板 Agent 运行时；署名=契约工位名）
// DEV-0052：self_check 如实透传写手自检结果（旧版硬编码 'pass'）；重写/修复轮同样登记
const regRun = (agentName: string, selfCheck = "pass") =>
  world.run("python3", [
    "-c",
    [
      "import sys",
      `sys.path.insert(0, '${REPO}/rules')`,
      "import store; store.init()",
      "print(store.register_run(agent=sys.argv[1], bid_id=sys.argv[2], self_check=(sys.argv[3] or None)))",
    ].join("; "),
    agentName,
    BID,
    selfCheck,
  ]);
for (const d of drafts) await regRun(`bid-writer:${d.chapter}`, d.selfCheckOk ? "pass" : "flagged");

phase("逐章机检，不达标打回重写");
let rewriteDispatches = 0;
for (let round = 1; round <= MAX_REWRITE_ROUNDS; round++) {
  const checks = await Promise.all(
    chapters.map((c) =>
      world.run("python3", ["rules/verify_draft.py", "--bid", BID, "--chapter", c.chapter, "--json"]),
    ),
  );
  const failures: { ch: string; report: string }[] = [];
  for (let i = 0; i < chapters.length; i++) {
    const c = chapters[i];
    const r = checks[i];
    if (!c || !r) continue;
    if (r.exitCode === 0) {
      report({ chapter: c.chapter, status: "机检通过", note: "verify_draft PASS" }, "progress");
    } else {
      failures.push({ ch: c.chapter, report: (r.stderr || r.stdout).slice(-1200) });
    }
  }
  if (failures.length === 0) break;
  log(`第 ${round} 轮机检：${failures.length} 章未过，打回重写`);
  await Promise.all(
    failures.map((f) => {
      const w = writerFor(f.ch);
      if (!w) throw new Error(`章节 ${f.ch} 没有对应写手`);
      rewriteDispatches++;
      return w.ask(`verify_draft 机检未通过，报告如下。修好草稿对应问题后再回复机检要点：\n${f.report}`);
    }),
  );
}
// DEV-0052 遥测：重写轮派发补登记（旧版漏计——写手实际调用次数被低估）
for (let i = 0; i < rewriteDispatches; i++) await regRun("bid-writer", "rewrite-round");

phase("定位抽查：引用逐字回到原文");
const locator = agent("bid-locator", {
  system:
    "你是 bid-master 的 bid-locator：对产物引用与招标文件原文做逐字二次定位抽查，只读不写。" +
    "开工先读 /Users/duke/bid-master/skills/bid-locate/SKILL.md。" +
    "输出 hit_rate 报告：抽查条数、命中条数、命中率、每条未命中项的章节与差在哪。",
  tools: "readonly",
  model: "lite",
});
let located: LocateResult | undefined;
for (let round = 0; round < MAX_LOCATE_ROUNDS; round++) {
  located = await locator.ask<LocateResult>(
    round === 0
      ? `对 ~/.bidmaster/bids/${BID}/draft/ch-*.md 做二次定位抽查，逐字核对每条引用与 ~/.bidmaster/bids/${BID}/source/ 原文的一致性。`
      : `上一轮有未命中项且已修复，再抽查一轮：${JSON.stringify(located?.misses ?? [])}`,
  );
  if (located.hitRate >= MIN_HIT_RATE) break;
  log(`定位命中率 ${located.hitRate}，未命中 ${located.misses.length} 条，交回写手修正`);
  await Promise.all(
    located.misses.map((m) => {
      const w = writerFor(m.chapter);
      if (!w) return Promise.resolve();
      return w.ask(`定位抽查未命中：${m.detail}。修正引用，或删掉这条没有原文支撑的断言。`);
    }),
  );
}
if (!located) throw new Error("定位抽查未执行");
await regRun("bid-locator");

// 审计报告由脚本落盘并登记（auditor 只读，写动作归确定性脚本）
const persistAudit = (rep: {
  bid_id: string;
  round: number;
  findings: { where: string; severity: string; what: string; chapter: string; cite: { quote: string } }[];
  stats: Record<string, number>;
  status: string;
  producer: string;
}) =>
  world.run("python3", [
    "-c",
    [
      "import json,sys",
      "from pathlib import Path",
      `sys.path.insert(0, '${REPO}/rules')`,
      "import store; store.init()",
      "bid = sys.argv[1]",
      "rep = json.loads(sys.argv[2])",
      `p = Path.home() / '.bidmaster/bids' / bid / 'audit' / ('audit-r%d.json' % rep['round'])`,
      "p.parent.mkdir(parents=True, exist_ok=True)",
      "p.write_text(json.dumps(rep, ensure_ascii=False, indent=2) + '\\n', encoding='utf-8')",
      "print(json.dumps(store.register_artifact(bid, 'audit', str(p), status='registered', producer='bid-auditor'), ensure_ascii=False))",
    ].join("; "),
    BID,
    JSON.stringify(rep),
  ]);

phase("对抗审查：找茬、落盘、机检闭环");
const auditor = agent("bid-auditor", {
  system:
    "你是 bid-master 的 bid-auditor：对抗审查，只找茬不写作。开工先读 /Users/duke/bid-master/skills/bid-audit/SKILL.md。" +
    "每条缺陷必须带：被审文件路径 where、逐字摘录 quote、章节 ID（跨章填 all）。" +
    "quote 只能从 draft/*.md 正文逐字复制（机检 verify_audit 只读这些文件）；manifest 等非草稿文件的问题，where 写该文件、quote 留空字符串。" +
    "severity 只在会直接导致废标或评审硬伤时才标 blocking。",
  tools: "readonly",
  model: "lite",
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
        ? `审查 ~/.bidmaster/bids/${BID}/draft/ 下各章草稿：废标风险、评审硬伤、与规格单评分点的错漏。`
        : `上一轮报告有 quote 无法在 draft/*.md 逐字定位：\n${citeFeedback}\n请重新输出整份报告，quote 一律从 draft/*.md 正文逐字复制，非草稿文件的问题 quote 留空。`,
    );
    await regRun("bid-auditor");
    const persisted = await persistAudit({
      bid_id: BID,
      round: auditRound,
      findings: audit.findings.map((f) => ({
        where: f.where,
        severity: f.severity,
        what: f.what,
        chapter: f.chapter,
        cite: { quote: f.quote },
      })),
      stats: { total: audit.total, blocking: audit.blocking },
      status: "registered",
      producer: "bid-auditor",
    });
    if (persisted.exitCode !== 0) throw new Error(`审计报告落盘/登记失败：${persisted.stderr.slice(0, 300)}`);
  }
  // 谁审查审查者：auditor 的 quote 是否逐字存在、草稿引文是否逐字，由 verify_audit.py 机检说了算
  const recheck = await world.run("python3", ["rules/verify_audit.py", "--bid", BID, "--round", String(auditRound), "--json"]);
  if (recheck.exitCode === 0) {
    auditPassed = true;
    break;
  }
  // DEV-0052：按 verify_audit 结构化 error_items 分类路由（旧版靠错误文案字符串前缀耦合，
  // 机检措辞一改路由就静默失效）；无分类的历史版本回退到旧字符串匹配
  let errors: string[] = [];
  let citeErrs: string[] = [];
  let reqErrs: string[] = [];
  let reqBySp: Record<string, string[]> = {};
  try {
    const parsed: AuditCheck & { error_items?: { class: string; sp_id?: string; message: string }[] } = JSON.parse(recheck.stdout);
    errors = parsed.errors ?? [];
    const items = parsed.error_items;
    if (items && items.length > 0) {
      citeErrs = items.filter((e) => e.class === "cite_missing" || e.class === "missing_report").map((e) => e.message);
      for (const e of items.filter((x) => x.class === "scoring_point")) {
        reqErrs.push(e.message);
        if (e.sp_id) (reqBySp[e.sp_id] ??= []).push(e.message);
      }
    } else {
      citeErrs = errors.filter((e) => e.startsWith("cite 不存在") || e.startsWith("缺审计报告"));
      reqErrs = errors.filter((e) => e.includes("评分点"));
    }
  } catch {
    errors = [(recheck.stderr || recheck.stdout).slice(-800)];
    citeErrs = errors;
  }
  log(`verify_audit round ${auditRound} 未过：审计引用问题 ${citeErrs.length} 条，草稿引文问题 ${reqErrs.length} 条`);
  if (iter === MAX_AUDIT_ITERS) throw new Error(`verify_audit 仍不通过（round ${auditRound}），报告在 verify/ 下，需人工介入：${errors.join(" | ").slice(0, 400)}`);
  // 草稿引文问题 → 对应章写手（优先结构化 sp_id 映射，历史回退正则抓 SP id）
  if (reqErrs.length > 0) {
    const reqByChapter: Record<string, string[]> = {};
    for (const [spId, msgs] of Object.entries(reqBySp)) {
      const ch = spChapter[spId];
      (reqByChapter[ch ?? "all"] ??= []).push(...msgs);
    }
    for (const e of reqErrs) {
      if (reqBySp && Object.values(reqBySp).some((msgs) => msgs.includes(e))) continue;
      const m = /评分点 (SP-[A-Za-z0-9]+)/.exec(e);
      const spId = m?.[1];
      const ch = spId === undefined ? undefined : spChapter[spId];
      (reqByChapter[ch ?? "all"] ??= []).push(e);
    }
    await Promise.all(
      Object.entries(reqByChapter).map(([ch, errs]) => {
        const targets = ch === "all" ? writers.map((x) => x.w) : [writerFor(ch)];
        return Promise.all(
          targets.map((w) =>
            w
              ? w.ask(
                  "verify_audit 机检要求：草稿「评分点响应」段中的招标要求引文必须与规格单 requirement 逐字一致（不得截断/改写）。" +
                    `以下评分点未通过，请把规格单里该评分点的 requirement 原文逐字写进对应响应段，并顺手确认 manifest 的 ticket_id 非空：\n${errs.join("\n")}`,
                )
              : Promise.resolve(),
          ),
        );
      }),
    );
    rewriteDispatches += Object.keys(reqByChapter).length;
  }
  // DEV-0052：写手修复后强制重审（旧版仅草稿问题时不重审——交付的 findings 可能引用修复前文本）
  needAudit = citeErrs.length > 0 || reqErrs.length > 0;
  citeFeedback = citeErrs.join("\n");
}
if (!audit || !auditPassed) throw new Error("对抗审查未通过机检");
const auditPassRound = auditRound;

// blocking 缺陷去重后上报一次（随发生随上报，中途失败也不丢）
const seen = new Set<string>();
const blocking = audit.findings.filter((f) => {
  if (f.severity !== "blocking") return false;
  const key = `${f.where}|${f.quote}`;
  if (seen.has(key)) return false;
  seen.add(key);
  return true;
});
for (const f of blocking) report(f);

if (blocking.length > 0) {
  const targets = new Set<string>();
  for (const f of blocking) {
    if (f.chapter === "all") {
      for (const c of chapters) targets.add(c.chapter);
    } else {
      targets.add(f.chapter);
    }
  }
  await Promise.all(
    [...targets].map((ch) => {
      const w = writerFor(ch);
      if (!w) return Promise.resolve();
      const mine = blocking.filter((f) => f.chapter === ch || f.chapter === "all");
      return w.ask(
        `对抗审查发现 ${mine.length} 条废标级缺陷，请逐条修复草稿（没有我方证据支撑的承诺/佐证一律删除或改为规格单素材可支撑的表述，不得新增断言）：\n${JSON.stringify(mine)}`,
      );
    }),
  );
}

phase("终检、登记、交付报告");
// 修复后的草稿全量终检；草稿与 manifest 统一登记（reconcile 登记制要求）
const finalDraft = await world.run("python3", ["rules/verify_draft.py", "--bid", BID, "--all", "--json"]);
const register = await world.run("python3", [
  "-c",
  [
    "import json,sys",
    "from pathlib import Path",
    `sys.path.insert(0, '${REPO}/rules')`,
    "import store; store.init()",
    "bid = sys.argv[1]",
    "ws = Path.home() / '.bidmaster/bids' / bid",
    "out = []",
    "for pat in ('draft/*.md', 'draft/*.manifest.json'):",
    "    for f in sorted(ws.glob(pat)):",
    "        out.append({'file': f.name, 'kind': 'draft', **store.register_artifact(bid, 'draft', str(f), producer='bid-writer')})",
    "print(json.dumps(out, ensure_ascii=False))",
  ].join("\n"),
  BID,
]);
if (register.exitCode !== 0) log(`草稿登记告警：${register.stderr.slice(0, 200)}`);
const hitRate = located.hitRate;
await artifact.markdown(
  "report",
  [
    `# 技术标生产报告 · ${BID}`,
    "",
    `- 章节数：${chapters.length}；终检 verify_draft：${finalDraft.exitCode === 0 ? "全部通过" : "存在违规，看 ~/.bidmaster/bids/" + BID + "/verify/ 报告"}`,
    `- verify_audit 引文一致性机检：round ${auditPassRound} 通过`,
    `- 定位抽查：${located.hits}/${located.sampled} 命中（${hitRate}）`,
    `- 对抗审查：共 ${audit.total} 条缺陷，废标级 ${blocking.length} 条（已交写手修复）`,
    ...(blocking.length > 0 ? [`- 注意：以上 findings 产生于废标级修复之前；修复后的草稿以 verify_draft 全量终检为机器结论，未重跑对抗审查。`] : []),
    "",
    ...audit.findings.map((f) => `- **[${f.severity}]** ${f.what}（${f.where}${f.quote ? "：「" + f.quote.slice(0, 40) + "」" : ""}）`),
    "",
    "> S5→S6 人工签核（set_stage.py --sign-off）未代办，放行由 owner 决定。",
  ].join("\n"),
  { title: `技术标生产报告 · ${BID}` },
);
// DEV-0052：终检阻塞化——旧版终检失败仅写进报告文本仍以成功形状返回（run 不标失败），
// 修复阶段回归的章节不会被发现。报告已落盘留证后再 throw。
if (finalDraft.exitCode !== 0) {
  throw new Error(`verify_draft --all 终检未通过（修复阶段可能有章节回归）：报告已落盘，明细见 ~/.bidmaster/bids/${BID}/verify/`);
}
const result: WorkflowReport = {
  conclusion: `${BID} 共 ${chapters.length} 章；定位命中率 ${hitRate}；对抗审查废标级缺陷 ${blocking.length} 条已交写手修复；verify_audit 于 round ${auditPassRound} 通过；verify_draft 全量终检通过（终检失败即中止交付）。`,
  findings: audit.findings,
  verified: [
    "每章草稿过 rules/verify_draft.py 机检（退出码 0）",
    `rules/verify_audit.py 对审计引用与草稿引文做逐字复核（round ${auditPassRound} 通过）`,
    `bid-locator 只读抽查 ${located.sampled} 条引用定位，门限 ${MIN_HIT_RATE}`,
    "修复后全量 verify_draft --all 终检",
    "草稿/manifest/审计报告已按登记制写入 truth.db（register_artifact）",
  ],
  notCovered: [
    "S5→S6 人工签核（set_stage.py --sign-off）——本流水线不代办，放行由 owner 决定",
    "素材一致性（gates 的 material_match）依赖人工确认",
    "状态推进（set_stage）未执行——看板状态仍以人工操作为准",
  ],
};
return result;