/* zcode-workflow
description: bid-master 标讯初筛流水线：读 leads/raw 增量→指纹去重→并行三分类打分（evidence
  必填）→校准员查尺度→validate_leads.py 机检闭环，只写 leads 暂存区，转正归人工
args:
  limit:
    type: number
    description: 单批最多初筛的未见过标讯条数
    required: false
    default: 10
*/
// ============ bid-master 标讯初筛流水线（S2 前）============
// 关联契约：contracts/workflows/lead-scout-triage.json
// 输入：~/.bidmaster/leads/raw/*.jsonl 增量（对照 leads.seen 判重）
// 输出：~/.bidmaster/leads/scored-batch-<时间戳>.jsonl 批次存档（保留最近 10 批）
//       + scored-batch.jsonl（最新批视图，人工转正流程路径不变）
//       转正 lead.promote 归人工，本流水线不碰 bids/ 与 leads.seen

const REPO = "/Users/duke/bid-master";

interface LeadRow {
  /** 标讯标题 */
  title: string;
  /** 原始链接（判重键） */
  source_url: string;
  /** 原始行完整 JSON，透传给 scout */
  raw: string;
}
interface ScoredLead {
  /** 本批内唯一 id（脚本回填为 s-序号） */
  id?: string;
  title: string;
  source_url: string;
  /** YYYY-MM-DD 或 null，缺就 null 不编造 */
  published_at?: string | null;
  deadline?: string | null;
  amount?: number | null;
  industry?: string | null;
  region?: string | null;
  /** 0-100 */
  score: number;
  /** 三分类 */
  recommend: "纳入" | "观察" | "排除" | "重复";
  /** 纳入/观察必填：原始来源页关键句逐字摘录 + URL */
  evidence: { quote: string; url: string };
  /** 打分理由，引用画像维度 */
  reason: string;
  producer?: string;
  /** ISO8601 */
  ts?: string;
}
interface Calibration {
  /** 尺度有问题需要重看的行 id 与问题 */
  flags: { id: string; note: string }[];
}
interface WorkflowReport {
  conclusion: string;
  verified: string[];
  notCovered: string[];
}

const LIMIT = Number(args.limit ?? 10);
const MAX_FIX_ROUNDS = 2;

// DEV-0052 遥测：工位 run 由编排器登记（DEV-0041 纪律补齐到本流水线；self_check 如实透传）
const regRun = (agentName: string, selfCheck: string) =>
  world.run("python3", [
    "-c",
    [
      "import sys",
      "sys.path.insert(0, sys.argv[3])",
      "import store; store.init()",
      "print(store.register_run(agent=sys.argv[1], bid_id=None, self_check=(sys.argv[2] or None)))",
    ].join("; "),
    agentName,
    selfCheck,
    `${REPO}/rules`,
  ]);

artifact.table("triage", {
  title: "标讯初筛结果",
  key: "source_url",
  columns: [
    { field: "title", label: "标题" },
    { field: "recommend", label: "分类" },
    { field: "score", label: "分" },
    { field: "reason", label: "理由" },
  ],
});

phase("读入待初筛标讯，URL 判重");
const readLeads = await world.run("python3", [
  "-c",
  [
    "import json,sys",
    "from pathlib import Path",
    "home = Path.home()",
    "seen = set()",
    "seen_p = home / '.bidmaster/leads/leads.seen'",
    "if seen_p.exists():",
    "    seen = {ln.split('#', 1)[0].strip() for ln in seen_p.read_text(encoding='utf-8').splitlines() if ln.strip()}",
    "rows, seen_urls = [], set()",
    "raw_dir = home / '.bidmaster/leads/raw'",
    "if raw_dir.exists():",
    "    for f in sorted(raw_dir.glob('*.jsonl')):",
    "        for ln in f.read_text(encoding='utf-8').splitlines():",
    "            ln = ln.strip()",
    "            if not ln: continue",
    "            try: d = json.loads(ln)",
    "            except Exception: continue",
    "            url = str(d.get('source_url') or d.get('url') or '')",
    "            if not url or url in seen or url in seen_urls: continue",
    "            seen_urls.add(url)",
    "            rows.append({'title': str(d.get('title') or '')[:120], 'source_url': url, 'raw': ln})",
    "print(json.dumps(rows[:int(sys.argv[1])], ensure_ascii=False))",
  ].join("\n"),
  String(LIMIT),
]);
if (readLeads.exitCode !== 0) throw new Error(`读 leads 失败：${readLeads.stderr.slice(0, 300)}`);
const fresh: LeadRow[] = JSON.parse(readLeads.stdout.trim());
log(`待初筛标讯 ${fresh.length} 条（上限 ${LIMIT}）`);
if (fresh.length === 0) {
  const none: WorkflowReport = {
    conclusion: "没有未见过的新标讯，本轮无需初筛。",
    verified: ["对照 leads.seen 判重后增量为 0"],
    notCovered: [],
  };
  return none;
}

phase("并行三分类打分（evidence 必填）");
const scored = await Promise.all(
  fresh.map((row, i) => {
    const scout = agent(`bid-scout-第${i + 1}条`, {
      system:
        "你是 bid-master 的 bid-scout：漏斗第一道闸，把原始标讯变成可决策的线索候选，宁缺毋滥。" +
        "开工必读 /Users/duke/bid-master/skills/bid-scout/SKILL.md 与 ~/.bidmaster/memory/lessons.md。" +
        "工艺：画像（行业=金融/领域=网络安全服务）三分类打分；纳入=强匹配，观察=沾边但信息不足，排除=明显不符且 100% 带原因。" +
        "纳入与观察必附 evidence（来源 URL + 关键句逐字摘录，只认原始来源）；缺失字段一律 null，不编造；ts 填当前 ISO8601 时间。" +
        "你只产出结构化结论，落盘由流水线脚本完成。",
      tools: "readonly",
      model: "lite",
    });
    return scout.ask<ScoredLead>(
      `初筛这条标讯，按 SKILL.md 工艺输出完整线索 JSON（字段缺失填 null）：\n${row.raw}`,
    );
  }),
);
for (const s of scored) {
  report({ title: s.title, recommend: s.recommend, score: s.score, reason: s.reason }, "triage");
}

phase("校准员查三分类尺度");
const calibrator = agent("校准员", {
  system: "你是打分校准员：只对照 bid-scout 画像口径检查这批结论的三分类与分值尺度是否一致，找有问题的一行，不改内容。",
  tools: "none",
  model: "lite",
});
let rows = scored.map((s, i) => ({ ...s, id: `s-${i + 1}` }));
let calRounds = 0;
let calFlagged = false;
for (let round = 0; round < MAX_FIX_ROUNDS; round++) {
  const cal = await calibrator.ask<Calibration>(
    `画像口径：行业=金融（银行/证券/基金/期货）·领域=网络安全服务。逐行检查以下结论，只返回尺度有问题的行（id+问题一句话），没有问题返回空数组：\n${JSON.stringify(rows)}`,
  );
  calRounds++;
  if (!cal.flags || cal.flags.length === 0) break;
  calFlagged = true;
  log(`校准员标记 ${cal.flags.length} 行，退回对应 scout 重看`);
  const byId = new Map(rows.map((r) => [r.id ?? "", r]));
  await Promise.all(
    cal.flags.map((f) => {
      const row = byId.get(f.id);
      const idx = Number((f.id ?? "").split("-")[1]) - 1;
      if (!row || Number.isNaN(idx)) return Promise.resolve();
      const raw = fresh[idx]?.raw ?? "";
      const original = agent(`bid-scout-第${idx + 1}条`, {
        system:
          "你是 bid-master 的 bid-scout：漏斗第一道闸，宁缺毋滥。开工必读 skills/bid-scout/SKILL.md 与 ~/.bidmaster/memory/lessons.md；缺失字段 null 不编造。",
        tools: "readonly",
        model: "lite",
      });
      return original
        .ask<ScoredLead>(`校准员认为你这条的打分尺度有问题：${f.note}\n原始标讯：\n${raw}\n重新输出完整线索 JSON。`)
        .then((fixed) => {
          const j = rows.findIndex((r) => r.id === f.id);
          if (j >= 0) rows[j] = { ...fixed, id: f.id };
        });
    }),
  );
}
// DEV-0052 遥测：scout 首轮派发 N 条 + 校准员每轮一条，self_check 按校准结果如实登记
await Promise.all(rows.map((r) => regRun("bid-scout", calFlagged ? "flagged" : "pass")));
for (let i = 0; i < calRounds; i++) await regRun("校准员", calFlagged ? "flagged" : "pass");

phase("写暂存区并过 validate_leads 机检");
let lastCheck = { exitCode: 1, stdout: "", stderr: "" };
let fixDispatches = 0;
// DEV-0052：批次化落盘——带时间戳存档（保留最近 10 批）+ scored-batch.jsonl 仅作最新批视图，
// 修复了旧版 'w' 覆盖写导致上一批未转正即丢失的数据丢失缺陷
const BATCH_STAMP = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
let batchPath = "";
for (let round = 1; round <= MAX_FIX_ROUNDS + 1; round++) {
  const write = await world.run("python3", [
    "-c",
    [
      "import json,sys,hashlib",
      "from pathlib import Path",
      "rows = json.loads(sys.argv[1])",
      "leads = Path.home() / '.bidmaster/leads'",
      "batch = leads / ('scored-batch-' + sys.argv[2] + '.jsonl')",
      "batch.parent.mkdir(parents=True, exist_ok=True)",
      "lines = []",
      "for r in rows:",
      "    fp = 'sha256:' + hashlib.sha256(str(r.get('source_url','')).strip().lower().encode('utf-8')).hexdigest()",
      "    rec = {'id': r.get('id'), 'title': r.get('title'), 'source_url': r.get('source_url'),",
      "           'fingerprint': fp, 'published_at': r.get('published_at'), 'deadline': r.get('deadline'),",
      "           'amount': r.get('amount'), 'industry': r.get('industry'), 'region': r.get('region'),",
      "           'score': r.get('score', 0), 'recommend': r.get('recommend'),",
      "           'evidence': r.get('evidence') or {}, 'reason': r.get('reason'),",
      "           'producer': 'bid-scout', 'ts': r.get('ts')}",
      "    lines.append(json.dumps(rec, ensure_ascii=False))",
      "text = chr(10).join(lines) + chr(10)",
      "batch.write_text(text, encoding='utf-8')",
      "(leads / 'scored-batch.jsonl').write_text(text, encoding='utf-8')",
      "batches = sorted(leads.glob('scored-batch-*.jsonl'))",
      "for old in batches[:-10]: old.unlink()",
      "print(str(batch))",
    ].join("\n"),
    JSON.stringify(rows),
    BATCH_STAMP,
  ]);
  if (write.exitCode !== 0) throw new Error(`写暂存区失败：${write.stderr.slice(0, 300)}`);
  batchPath = write.stdout.trim();
  lastCheck = await world.run("python3", ["rules/validate_leads.py", "--file", batchPath, "--json"]);
  if (lastCheck.exitCode === 0) break;
  const isLastRound = round === MAX_FIX_ROUNDS + 1;
  if (isLastRound) {
    // 末轮拦截：不再派发修复（旧版此处派发后丢弃结果），直接带原始错误失败
    log(`validate_leads 末轮（第 ${round} 轮）仍拦截，终止`);
    break;
  }
  log(`validate_leads 第 ${round} 轮拦截，按行退回 scout`);
  let problems: { index?: number; error?: string }[] = [];
  try {
    problems = JSON.parse(lastCheck.stdout).problems ?? [];
  } catch {
    problems = [];
    log(`机检输出无法解析为行级问题：${(lastCheck.stderr || lastCheck.stdout).slice(-300)}`);
  }
  await Promise.all(
    problems.map((p) => {
      // DEV-0052：无行号的问题不再错误路由到 rows[0]，如实跳过（末轮整体失败兜底）
      const row = p.index !== undefined ? rows[p.index] : undefined;
      if (!row) {
        log(`机检问题缺行号（${(p.error ?? "").slice(0, 60)}），跳过定向修复`);
        return Promise.resolve();
      }
      const idx = rows.findIndex((r) => r.id === row.id);
      const original = agent(`bid-scout-第${idx + 1}条`, {
        system: "你是 bid-master 的 bid-scout。开工必读 skills/bid-scout/SKILL.md；缺字段 null 不编造；排除行必带原因。",
        tools: "readonly",
        model: "lite",
      });
      fixDispatches++;
      return original
        .ask<ScoredLead>(
          `validate_leads 机检拦截：${p.error ?? "schema 不合规"}\n原始标讯：\n${fresh[idx]?.raw ?? ""}\n修正后重新输出完整线索 JSON。`,
        )
        .then((fixed) => {
          if (idx >= 0) rows[idx] = { ...fixed, id: row.id };
        });
    }),
  );
}
if (lastCheck.exitCode !== 0) throw new Error(`validate_leads 仍不通过：${(lastCheck.stderr || lastCheck.stdout).slice(-400)}`);
// DEV-0052 遥测：机检修复派发如实登记（通过=pass / 失败=fail）
for (let i = 0; i < fixDispatches; i++) {
  await regRun("bid-scout", lastCheck.exitCode === 0 ? "pass" : "fail");
}

const nIn = rows.filter((r) => r.recommend === "纳入").length;
const nWatch = rows.filter((r) => r.recommend === "观察").length;
const nDrop = rows.filter((r) => r.recommend === "排除" || r.recommend === "重复").length;
const result: WorkflowReport = {
  conclusion: `本批 ${rows.length} 条标讯初筛完成：纳入 ${nIn}、观察 ${nWatch}、排除/重复 ${nDrop}；validate_leads 机检通过，批次存档 ${batchPath}（最新批视图 ~/.bidmaster/leads/scored-batch.jsonl），转正（lead.promote）等人工确认。`,
  verified: [
    "对照 ~/.bidmaster/leads/leads.seen 做了 URL 增量判重",
    "rules/validate_leads.py 机检通过（evidence 非空/指纹去重/排除带原因/schema 必填）",
    "校准员对三分类与分值尺度做了一致性复核",
  ],
  notCovered: [
    "原始来源页的在线核实（本环境无联网工具，evidence 只对暂存文本逐字）",
    "转正写入 bids/ 与 leads.seen 更新——归人工 lead.promote 流程",
  ],
};
return result;