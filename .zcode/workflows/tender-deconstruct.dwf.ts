/* zcode-workflow
description: bid-master 招标解构流水线（S2→S4）：阶段0 商机评估→S2→S3 门禁→阶段1
  并行解构（响应矩阵/废标清单/应答骨架/命中台账100%对账）→阶段2 价格分析→规格单+完整性核验→S3→S4 门禁，actor 对齐
  bid-master 主链路工艺与 lessons
args:
  bidId:
    type: string
    description: "bid\r\r ID\r\r（已在\r\r S2\r\r 建档且\r\r source\r\r/tender\r\r.txt\r\r
      就绪\r\r）\r\r，如\r\r 2026\r\r-REAL01\r\r-aqfw"
    required: true
*/
// ============ bid-master 招标解构流水线 v1（S2→S4 段）============
// 关联契约：contracts/workflows/tender-deconstruct.json
// 输入：bid 已在 S2 建档、source/tender.txt 已就绪
// 产出：stage0.json/md、response_matrix.json、废标清单、应答骨架、hits_recon.json、
//       price.json、stage2 分析、spec.json、completeness.json，并推进到 S4
// 边界：不代办人工位；L3 红线不落盘；引用一律 [P#] 页码 + 单段内逐字摘录（L-1/L-3）

interface Lessons {
  /** 教训条目 */
  lessons: { id: string; scenario: string; lesson: string }[];
  /** 招标文本行数 */
  lines: number;
  /** ★/▲/实质性/否决 类标记行数（含全角变体） */
  marks: number;
}
interface Stage0Result {
  /** data/stage0.json 落盘路径 */
  json_path: string;
  /** stage0_商机评估.md 落盘路径 */
  md_path: string;
  positioning: string;
  decision: string;
  lessons_applied: string[];
}
interface DestructureResult {
  /** 产物落盘路径 */
  path: string;
  /** 一句话摘要（给规格单装配用） */
  summary: string;
}
interface SpecResult {
  /** data/spec.json 落盘路径 */
  path: string;
  scoring_points: number;
  chapters: string[];
}
interface Completeness {
  /** PASS / FAIL */
  result: "PASS" | "FAIL";
  checks: { name: string; ok: boolean; detail: string }[];
}
interface WorkflowReport {
  conclusion: string;
  verified: string[];
  notCovered: string[];
}

const REPO = "/Users/duke/bid-master";
const BID = String(args.bidId ?? "");
if (!BID || !/^[A-Za-z0-9._-]+$/.test(BID)) throw new Error("需要合法 bidId");
const WS = `~/.bidmaster/bids/${BID}`;
const MAX_FIX_ROUNDS = 2;

artifact.table("progress", {
  title: "解构进度",
  key: "step",
  columns: [
    { field: "step", label: "步骤" },
    { field: "status", label: "状态" },
    { field: "note", label: "说明" },
  ],
});

// 登记器：所有产物写后立即 register_artifact（纪律 1）；路径以 ~ 开头由 python expanduser
// DEV-0052：登记失败直接 throw（旧版多数调用点不检查退出码，漏登记静默丢失）
const register = async (kind: string, path: string, producer: string) => {
  const r = await world.run("python3", [
    "-c",
    [
      "import sys",
      "from pathlib import Path",
      `sys.path.insert(0, '${REPO}/rules')`,
      "import store; store.init()",
      "print(store.register_artifact(sys.argv[1], sys.argv[2], str(Path(sys.argv[3]).expanduser()), status='final', producer=sys.argv[4]))",
    ].join("; "),
    BID,
    kind,
    path,
    producer,
  ]);
  if (r.exitCode !== 0) throw new Error(`登记失败（${kind} / ${producer}）：${r.stderr.slice(0, 200)}`);
  return r;
};

// DEV-0041 遥测：工位 run 由编排器强制登记（run 计数入看板 Agent 运行时；署名=工位名）
// DEV-0052：self_check 由调用点如实透传（旧版硬编码 'pass'），cwd 依赖收敛为绝对路径
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

phase("读取招标文本与教训库");
const scan = await world.run("python3", [
  "-c",
  [
    "import json,sys,re",
    "from pathlib import Path",
    "ws = Path.home() / '.bidmaster/bids' / sys.argv[1]",
    "txt = (ws / 'source' / 'tender.txt').read_text(encoding='utf-8', errors='replace')",
    "lines = txt.count(chr(10)) + 1",
    "marks = len(re.findall(r'[★☆▲△]|实质性|否决|无效|废标', txt))",
    `sys.path.insert(0, '${REPO}/rules')`,
    "import store; store.init()",
    "lessons = [{'id': r[0], 'scenario': r[1], 'lesson': r[2]} for r in store._conn().execute('SELECT id, scenario, lesson FROM lessons ORDER BY id')]",
    "print(json.dumps({'lines': lines, 'marks': marks, 'lessons': lessons}, ensure_ascii=False))",
  ].join("\n"),
  BID,
]);
if (scan.exitCode !== 0) throw new Error(`扫描失败：${scan.stderr.slice(0, 300)}`);
const facts: Lessons = JSON.parse(scan.stdout.trim());
log(`tender.txt ${facts.lines} 行 · 否决/★类标记 ${facts.marks} 处 · 教训库 ${facts.lessons.length} 条`);

phase("阶段0 商机评估，过 S2→S3 门禁");
let stage0: Stage0Result | undefined;
let s23feedback = "";
for (let round = 1; round <= MAX_FIX_ROUNDS + 1; round++) {
  const evaluator = agent("评估员-商机评估", {
    system:
      "你是 bid-master 主链路的商机评估工位（阶段0）。开工必读 /Users/duke/bid-master/skills/bid-master/SKILL.md 的阶段0工艺与 ~/.bidmaster/memory/lessons.md（重点 L-7：内定/陪标信号只能提示风险不能下结论，逐信号附招标文件原文定位）。" +
      "产出两份产物并自行落盘：① data/stage0.json——严格含字段 bid_id/stage_mark/positioning/signals[]/participation/lessons_applied[]/decision/status（status='final'，bid_id=" + BID + "，lessons_applied 引用真实教训 ID 如 L-7）；② stage0_商机评估.md——评估叙述，每个判断带 [P#] 页码与单段内逐字摘录。" +
      "L3 红线（成本价/折扣/客户名单明细/证件号/证书编号）绝不落盘；不得编造原文。" +
      "产物落盘后只回填路径；登记与署名由流水线编排器统一执行，不要自行调用 rules/store.py 的 register_artifact/register_run。",
  });
  stage0 = await evaluator.ask<Stage0Result>(
    `${round === 1 ? "对招标文件做阶段0商机评估。" : `上一轮被门禁拦下：${s23feedback}\n请修正后重新落盘两份产物。`}\n` +
      `招标文本：${WS}/source/tender.txt（${facts.lines} 行，否决/★类标记 ${facts.marks} 处）。` +
      `可用教训：${facts.lessons.map((l) => l.id).join(",")}。产物写入 ${WS}/data/ 与 ${WS}/ 下。`,
  );
  const r1 = await register("stage0", stage0.json_path, "bid-evaluator");
  if (r1.exitCode !== 0) throw new Error(`stage0.json 登记失败：${r1.stderr.slice(0, 200)}`);
  await register("draft", stage0.md_path, "bid-evaluator");
  const gate = await world.run("python3", ["rules/set_stage.py", "--bid", BID, "--to", "S3", "--json"]);
  if (gate.exitCode === 0) break;
  if (round > MAX_FIX_ROUNDS) throw new Error(`S2→S3 门禁仍拦截：${(gate.stderr || gate.stdout).slice(-300)}`);
  s23feedback = (gate.stderr || gate.stdout).slice(-400);
  log(`S2→S3 拦截（第 ${round} 轮）：${s23feedback.slice(0, 120)}`);
}
if (!stage0) throw new Error("阶段0 未完成");
// DEV-0052 遥测：评估员工位补登记（旧版漏登记——DEV-0041 覆盖缺口）；self_check=S2→S3 门禁实过
await regRun("评估员-商机评估");
report({ step: "阶段0 商机评估", status: "S3 已过", note: stage0.decision.slice(0, 60) }, "progress");

phase("阶段1 并行解构：矩阵 / 废标清单 / 应答骨架 / 命中台账");
const destructureSpecs = [
  {
    name: "解构-响应矩阵",
    task: "产出投标响应矩阵：逐条对应采购需求（第二章）与资格/实质性要求，输出 data/response_matrix.json（数组：{req_id, requirement, source_page, response_type: 完全响应|部分响应|需澄清, response_sketch}）与 stage1_响应矩阵.md。每条 requirement 带原文 [P#] 定位与单段内逐字摘录。",
  },
  {
    name: "解构-废标清单",
    task: "产出零遗漏废标风险清单 stage1_废标风险清单.md：扫描全文 ★/▲/实质性/否决/无效/废标 标记（含全角★☆▲△），逐条列 [P#] + 逐字摘录 + 触碰后果 + 我方应对；用命中台账口径自证零遗漏。",
  },
  {
    name: "解构-应答骨架",
    task: "产出按评分点展开的技术标应答骨架 stage1_技术标应答骨架.md：从评分办法提取每个评分点（含分值），映射到响应矩阵需求条目，给出章级应答骨架（建议章节切分 ch-A/ch-B/…，每章含哪些评分点）。",
  },
  {
    name: "解构-命中台账",
    task: "产出关键词命中台账 data/hits_recon.json：选取检索关键词（安全服务/运维/驻场/应急/重保/资质/业绩/人员/★条款/磋商/报价等），逐条 {keyword, status: 收录|排除, reason}，扫描命中数 = 收录数 + 排除数，覆盖率必须 100%（L-4/L-13：排除项逐条留痕理由）；同时输出可读版 stage1_命中台账.md。",
  },
];
const deconstructed = await Promise.all(
  destructureSpecs.map((s) => {
    const a = agent(s.name, {
      system:
        `你是 bid-master 主链路「${s.name}」工位（阶段1 招标解构）。开工必读 /Users/duke/bid-master/skills/bid-master/SKILL.md 的阶段1工艺与 ~/.bidmaster/memory/lessons.md（L-1 引文必须单段内逐字；L-3 [P#] 页码定位；L-2 磋商/须知类结构；L-4 台账对账；L-5 全角标记）。` +
        `产物自行落盘到 ${WS}/ 下并在回复中给出每个文件的绝对路径。L3 红线绝不落盘；规格单外的断言不新增；不得编造原文。` +
        `登记与署名由流水线编排器统一执行，不要自行调用 rules/store.py 的 register_artifact/register_run。`,
    });
    return a.ask<DestructureResult>(
      `${s.task}\n招标文本：${WS}/source/tender.txt（${facts.lines} 行）。`,
    );
  }),
);
for (const d of deconstructed) {
  report({ step: "阶段1 解构", status: "完成", note: d.summary.slice(0, 60) }, "progress");
}
for (const s of destructureSpecs) await regRun(s.name);
// 登记全部解构产物（response_matrix 按矩阵 kind，其余 md 按 draft；hits_recon 按契约）
// DEV-0052：预期产物缺失不再静默跳过（旧版 if f.exists() 会放过漏写产物的工位）——缺即 FAIL
const bulkReg = await world.run("python3", [
  "-c",
  [
    "import sys",
    "from pathlib import Path",
    `sys.path.insert(0, '${REPO}/rules')`,
    "import store; store.init()",
    "bid, ws = sys.argv[1], Path.home() / '.bidmaster/bids' / sys.argv[1]",
    "files = [('response_matrix', ws/'data'/'response_matrix.json', '解构-响应矩阵'),",
    "         ('draft', ws/'stage1_响应矩阵.md', '解构-响应矩阵'),",
    "         ('draft', ws/'stage1_废标风险清单.md', '解构-废标清单'),",
    "         ('draft', ws/'stage1_技术标应答骨架.md', '解构-应答骨架'),",
    "         ('hits_recon', ws/'data'/'hits_recon.json', '解构-命中台账'),",
    "         ('draft', ws/'stage1_命中台账.md', '解构-命中台账')]",
    "missing = [str(f) for _, f, _ in files if not f.exists()]",
    "if missing:",
    "    print('MISSING:' + ' | '.join(missing)); sys.exit(3)",
    "for kind, f, prod in files:",
    "    print(store.register_artifact(bid, kind, str(f), status='final', producer=prod))",
  ].join("\n"),
  BID,
]);
if (bulkReg.exitCode !== 0) throw new Error(`解构产物登记失败：${(bulkReg.stdout + bulkReg.stderr).slice(-400)}`);

phase("阶段2 价格分析");
const priceAgent = agent("价格分析师", {
  system:
    "你是 bid-master 主链路价格工位（阶段2）。开工必读 skills/bid-master/SKILL.md 阶段2工艺与 ~/.bidmaster/memory/lessons.md（L-6：先读评标办法价格分公式再算区间）。" +
    "产出 data/price.json（{bid_id, method, price_formula, baseline_model, range_suggestion, notes}）与 stage2_价格分析.md（公式逐字引用 + 区间推演）。L3 红线：不落盘我方成本价/底价，只做基于招标文件公式的区间推演。落盘后回填路径。",
});
const price = await priceAgent.ask<DestructureResult>(
  `招标文本：${WS}/source/tender.txt。评标办法与报价要求在其中，注意本项目是竞争性磋商。`,
);
await register("draft", price.path, "价格分析师");
await regRun("价格分析师");
report({ step: "阶段2 价格分析", status: "完成", note: price.summary.slice(0, 60) }, "progress");

phase("规格单装配 + 完整性核验闭环");
let spec: SpecResult | undefined;
let comp: Completeness | undefined;
let compFeedback = "";
for (let round = 1; round <= MAX_FIX_ROUNDS + 1; round++) {
  const assembler = agent("装配-规格单", {
    system:
      "你是 bid-master 规格单装配工位：把响应矩阵与应答骨架收敛成 verify_draft 可机检的规格单。" +
      "产出 data/spec.json：{bid_id, status:'final', scoring_points:[{id, chapter, requirement(逐字来自矩阵), cites:[P#]}], chapters:[{chapter, title, word_min, word_max}]}——评分点逐字 requirement 是 S5 机检红线（L-1）；章节切分沿应答骨架。" +
      "落盘后回填路径与统计。登记由编排器统一执行，不要自行调用 rules/store.py 的 register_artifact/register_run。",
  });
  spec = await assembler.ask<SpecResult>(
    `${round === 1 ? "装配规格单。" : `上一轮完整性核验未过：${compFeedback}\n请修正 spec.json 后重新落盘。`}\n` +
      `输入：${WS}/data/response_matrix.json、${WS}/stage1_技术标应答骨架.md、${WS}/data/price.json、招标文本 ${WS}/source/tender.txt。`,
  );
  await register("spec", spec.path, "装配-规格单");
  // 完整性核验（换人复核，不只自检）
  const checker = agent("核验-完整性", {
    system:
      "你是完整性核验员：独立核对规格单与解构产物的一致性（评分点覆盖矩阵需求？章节覆盖全部评分点？cites 是 [P#] 且在招标文本中存在？），只读不写，如实给 PASS/FAIL 与逐项 checks。",
    tools: "readonly",
    model: "lite",
  });
  comp = await checker.ask<Completeness>(
    `核对 ${WS}/data/spec.json 与 ${WS}/data/response_matrix.json、${WS}/stage1_技术标应答骨架.md、招标文本 ${WS}/source/tender.txt 的一致性，输出 {result, checks:[{name, ok, detail}]}。`,
  );
  const compPath = `${WS}/data/completeness.json`;
  const persist = await world.run("python3", [
    "-c",
    [
      "import json,sys",
      "from pathlib import Path",
      `sys.path.insert(0, '${REPO}/rules')`,
      "import store; store.init()",
      "bid = sys.argv[1]",
      "comp = json.loads(sys.argv[2])",
      "comp.update({'bid_id': bid, 'status': 'final'})",
      "p = Path.home() / '.bidmaster/bids' / bid / 'data' / 'completeness.json'",
      "p.write_text(json.dumps(comp, ensure_ascii=False, indent=2) + '\\n', encoding='utf-8')",
      "print(store.register_artifact(bid, 'completeness', str(p), status='final', producer='核验-完整性'))",
    ].join("\n"),
    BID,
    JSON.stringify(comp),
  ]);
  if (persist.exitCode !== 0) throw new Error(`completeness.json 落盘失败：${persist.stderr.slice(0, 200)}`);
  if (comp.result === "PASS") break;
  if (round > MAX_FIX_ROUNDS) throw new Error(`完整性核验仍 FAIL：${comp.checks.filter((c) => !c.ok).map((c) => c.detail).join(" | ").slice(0, 300)}`);
  compFeedback = comp.checks.filter((c) => !c.ok).map((c) => `${c.name}: ${c.detail}`).join("\n");
  log(`完整性核验 FAIL（第 ${round} 轮），退回装配工位`);
}
if (!spec || !comp || comp.result !== "PASS") throw new Error("规格单/完整性未闭环");
await regRun("装配-规格单");
await regRun("核验-完整性");
report({ step: "规格单+完整性", status: comp.result, note: `${spec.scoring_points} 评分点 / ${spec.chapters.length} 章` }, "progress");

phase("门禁 S3→S4 与交付");
let gateOk = false;
let gateFeedback = "";
let fixerRounds = 0;
for (let round = 1; round <= MAX_FIX_ROUNDS + 1; round++) {
  const gate = await world.run("python3", ["rules/set_stage.py", "--bid", BID, "--to", "S4", "--json"]);
  if (gate.exitCode === 0) {
    gateOk = true;
    break;
  }
  if (round > MAX_FIX_ROUNDS) throw new Error(`S3→S4 门禁仍拦截：${(gate.stderr || gate.stdout).slice(-400)}`);
  gateFeedback = (gate.stderr || gate.stdout).slice(-500);
  log(`S3→S4 拦截（第 ${round} 轮），退回命中台账工位修复`);
  const fixer = agent("解构-命中台账", {
    system: "你是 bid-master 命中台账工位。开工必读 skills/bid-master/SKILL.md 与 lessons（L-4/L-13）。修正 data/hits_recon.json 使对账覆盖率 100%（每条 keyword 带 status 收录|排除 + reason），落盘后回填。",
  });
  await fixer.ask(`门禁拦截：${gateFeedback}\n修正 ${WS}/data/hits_recon.json 后重新落盘。`);
  await register("hits_recon", `${WS}/data/hits_recon.json`, "解构-命中台账");
  fixerRounds++;
}
// DEV-0052 遥测：修复轮派发如实登记（旧版漏登记）；self_check 以门禁终局为准
for (let i = 0; i < fixerRounds; i++) await regRun("解构-命中台账", gateOk ? "pass" : "fail");
if (!gateOk) throw new Error("S3→S4 未通过");
await artifact.markdown(
  "report",
  [
    `# 招标解构交付 · ${BID}`,
    "",
    `- 已推进至 **S4 编制**（S2→S3 lessons 门禁、S3→S4 对账门禁均机检通过）`,
    `- 商机评估：${stage0.positioning.slice(0, 50)}…`,
    `- 解构产物：响应矩阵 / 废标清单 / 应答骨架 / 命中台账（对账 100%）`,
    `- 价格分析：${price.summary.slice(0, 50)}`,
    `- 规格单：${spec.scoring_points} 个评分点 / ${spec.chapters.length} 章（完整性核验 PASS）`,
    "",
    "> 下一步：跑 tech-proposal-pipeline 工作流（S4→S5 生产段）；S5→S6 封标签核归人工。",
  ].join("\n"),
  { title: `招标解构交付 · ${BID}` },
);
const result: WorkflowReport = {
  conclusion: `${BID} 已从 S2 推进到 S4：商机评估、四类解构产物（对账 100%）、价格分析、规格单（完整性 PASS）全部完成并按登记制入库；可接 tech-proposal-pipeline 进入编制段。`,
  verified: [
    "S2→S3 门禁（lessons_applied 教训 ID 真实性）由 set_stage 机检通过",
    "S3→S4 门禁（hits_recon 对账覆盖率 100%）由 set_stage 机检通过",
    "完整性核验由独立只读核验员给出 PASS（非装配工位自检）",
    "全部产物 register_artifact 登记（stage0/hits_recon/spec/completeness 走契约校验）",
  ],
  notCovered: [
    "商机评估为风险提示而非参与决策——是否投标由 owner 拍板",
    ".doc→txt 的表格线性化损失（txt 表格丢失为已知限制，响应矩阵以文字口径重建）",
    "S4→S5 生产段与 S5→S6 签核不在本流水线",
  ],
};
return result;