/* zcode-workflow
description: bid-master 归档提案流水线 v1.1（S8→S9 段）：汇集证据→archivist 复盘提案（supersession
  必填）→落盘 archive/→desensitize.py 脱敏机检闭环→登记，只提案不落库；v1.1 加 bidId 格式白名单
args:
  bidId:
    type: string
    description: 已开标待归档的 bid ID（如 2026-GOLD-jishu-wftest）
    required: true
  reason:
    type: string
    description: 开标结果原因一句话（如：技术分差 3 分落标，主因 X）
    required: false
  result:
    type: string
    description: 开标结果：win / loss / no-bid
    required: true
*/
// ============ bid-master 归档提案流水线 v1.1（S8→S9 段）============
// 关联契约：contracts/workflows/archive-close-proposal.json
// 输入：bids/<bidId>/ 全目录 + 开标结果（args.result / args.reason）
// 输出：archive/proposal.json + archive/lessons-draft.md（只提案，不落库）
// 边界：绝不写 kb/ 与 ~/.bidmaster/memory/；不执行 apply_archive（人工确认后触发）
// 安全：bidId 只经 argv 传给 python（不拼进 -c 代码串），并有格式白名单

interface Evidence {
  /** 证据文件相对 bids/<id>/ 的路径清单 */
  files: string[];
}
interface ArchivistResult {
  /** proposal.json 完整内容（契约：bid_id/result/cases/cert_changes/lessons/manual_confirm_list） */
  proposal: {
    bid_id: string;
    result: "win" | "loss" | "no-bid";
    producer?: string;
    cases: {
      name_alias: string;
      industry: string;
      year: number;
      scene: string[];
      slices_proposed: string[];
      valid_until: string;
    }[];
    cert_changes: { cert: string; change: string; affects: string[] }[];
    lessons: {
      id?: string;
      scenario: string;
      lesson: string;
      evidence: string;
      /** 「旧教训ID | 无」必填，防止教训库自相矛盾 */
      supersession: string;
      status?: string;
    }[];
    manual_confirm_list: string[];
  };
  /** lessons-draft.md 全文 */
  lessons_draft_md: string;
}
interface PersistOk {
  ok: boolean;
  /** archive 目录绝对路径（供脱敏机检） */
  dir?: string;
  problems?: string[];
}
interface WorkflowReport {
  conclusion: string;
  verified: string[];
  notCovered: string[];
}

const REPO = "/Users/duke/bid-master";
const BID = String(args.bidId ?? "");
const RESULT = String(args.result ?? "");
const REASON = String(args.reason ?? "");
if (!BID || !["win", "loss", "no-bid"].includes(RESULT)) {
  throw new Error("需要 bidId 与 result（win/loss/no-bid）");
}
if (!/^[A-Za-z0-9._-]+$/.test(BID)) throw new Error(`bidId 含非法字符（仅允许字母/数字/./_/-）：${BID}`);
const MAX_REDO_ROUNDS = 2;
// DEV-0052：RESULT/REASON 与 bidId 同等做输入白名单（旧版仅 bidId 加固，reason 直接进 prompt）
if (REASON.length > 400 || /[<>{}]/.test(REASON)) throw new Error("reason 超长或含非法字符（<>{}）");

// DEV-0052 遥测：archivist 工位 run 编排器登记（DEV-0041 覆盖缺口）；self_check 以脱敏机检终局如实透传
const regRun = (agentName: string, selfCheck: string) =>
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

phase("汇集 bids/<id> 证据清单");
const ev = await world.run("python3", [
  "-c",
  [
    "import json,sys",
    "from pathlib import Path",
    "ws = Path.home() / '.bidmaster/bids' / sys.argv[1]",
    "if not ws.exists():",
    "    print(json.dumps({'error': 'bid 目录不存在'}))",
    "    sys.exit(1)",
    "files = [str(p.relative_to(ws)) for p in sorted(ws.rglob('*')) if p.is_file() and 'source' not in p.parts]",
    "print(json.dumps({'files': files}, ensure_ascii=False))",
  ].join("\n"),
  BID,
]);
if (ev.exitCode !== 0) throw new Error(`证据汇集失败：${ev.stderr.slice(0, 300)}`);
const evidence: Evidence = JSON.parse(ev.stdout.trim());
log(`证据文件 ${evidence.files.length} 个`);

const archivist = agent("bid-archivist", {
  system:
    "你是 bid-master 的 bid-archivist：把一标的经历变成下一标能用的教训，只提案不落库。" +
    "开工先读 /Users/duke/bid-master/skills/bid-archive/SKILL.md。" +
    "铁律：只依据证据链归因，无 manifest 的旧条目标 evidence=partial；每条教训 supersession 必填（「旧教训ID | 无」）；" +
    "客户一律别名+行业；L3（证件号/证书编号/成本价/折扣/客户名单明细）绝不落盘；不替人做采纳决定。" +
    "产物 = proposal JSON + lessons-draft.md 全文，落盘由流水线脚本完成。",
});

phase("归档复盘提案 → 落盘登记 → 脱敏机检闭环");
let proposal: ArchivistResult | undefined;
let archiveDir = "";
let feedback = "";
let closed = false;
let archivistRounds = 0;
for (let round = 1; round <= MAX_REDO_ROUNDS + 1; round++) {
  proposal = await archivist.ask<ArchivistResult>(
    round === 1
      ? `对 bid ${BID} 做开标后复盘归档提案。开标结果：${RESULT}${REASON ? `（${REASON}）` : ""}。` +
          `证据文件（相对 bids/${BID}/）：\n${evidence.files.join("\n")}\n按 SKILL.md 工艺输出 proposal + lessons-draft.md。`
      : `上一轮提案被机检拦下：\n${feedback}\n请修正后重新输出完整 proposal + lessons-draft.md。`,
  );
  archivistRounds++;
  // 落盘 + supersession/evidence 完整性检查 + 登记（脚本确定性执行）
  const persist = await world.run("python3", [
    "-c",
    [
      "import json,sys",
      "from pathlib import Path",
      `sys.path.insert(0, '${REPO}/rules')`,
      "import store; store.init()",
      "bid = sys.argv[1]",
      "prop = json.loads(sys.argv[2])",
      "md = sys.argv[3]",
      "ws = Path.home() / '.bidmaster/bids' / bid / 'archive'",
      "ws.mkdir(parents=True, exist_ok=True)",
      "problems = []",
      "for i, l in enumerate(prop.get('lessons') or []):",
      "    if not str(l.get('supersession') or '').strip():",
      "        problems.append('lessons[%d] 缺 supersession（填旧教训ID 或 无）' % i)",
      "    if not str(l.get('evidence') or '').strip():",
      "        problems.append('lessons[%d] 缺 evidence 出处' % i)",
      "if problems:",
      "    print(json.dumps({'ok': False, 'problems': problems}, ensure_ascii=False))",
      "    sys.exit(1)",
      "pp = ws / 'proposal.json'",
      "pp.write_text(json.dumps(prop, ensure_ascii=False, indent=2) + '\\n', encoding='utf-8')",
      "(ws / 'lessons-draft.md').write_text(md, encoding='utf-8')",
      "reg = store.register_artifact(bid, 'proposal', str(pp), status='proposed', producer='bid-archivist')",
      "print(json.dumps({'ok': True, 'dir': str(ws), 'proposal': str(pp), 'register': reg}, ensure_ascii=False))",
    ].join("\n"),
    BID,
    JSON.stringify(proposal.proposal),
    proposal.lessons_draft_md,
  ]);
  if (persist.exitCode !== 0) {
    if (round > MAX_REDO_ROUNDS) throw new Error(`提案落盘/登记仍失败：${(persist.stderr || persist.stdout).slice(-400)}`);
    feedback = (persist.stdout || persist.stderr).slice(-600);
    log(`提案第 ${round} 轮被拦（supersession/evidence 不完整），退回 archivist`);
    continue;
  }
  const ok: PersistOk = JSON.parse(persist.stdout.trim());
  archiveDir = ok.dir ?? "";
  // 脱敏机检：命中即拦（报告里 PII 已打码），拦截率要求 100%
  const desens = await world.run("python3", ["rules/desensitize.py", archiveDir], { timeoutMs: 60000 });
  if (desens.exitCode === 0) {
    closed = true;
    break;
  }
  if (round > MAX_REDO_ROUNDS) throw new Error(`脱敏机检仍不通过：${(desens.stderr || desens.stdout).slice(-500)}`);
  feedback = (desens.stdout || desens.stderr).slice(-600);
  log(`脱敏机检第 ${round} 轮命中，退回 archivist 重写提案`);
}
if (!proposal || !closed) throw new Error("归档提案未通过脱敏机检");
for (let i = 0; i < archivistRounds; i++) await regRun("bid-archivist", closed ? "pass" : "fail");

phase("汇总待人工确认清单");
const nLessons = proposal.proposal.lessons?.length ?? 0;
const nCases = proposal.proposal.cases?.length ?? 0;
await artifact.markdown(
  "proposal-report",
  [
    `# 归档提案 · ${BID}（${RESULT}）`,
    "",
    `- 教训提案 ${nLessons} 条（supersession 全填）、案例提案 ${nCases} 条、证照变动 ${(proposal.proposal.cert_changes ?? []).length} 项`,
    `- 脱敏机检（desensitize.py）通过；产物在 ~/.bidmaster/bids/${BID}/archive/`,
    "",
    "## 待人工拍板",
    ...(proposal.proposal.manual_confirm_list ?? []).map((m) => `- [ ] ${m}`),
    "",
    "> 本流水线只提案不落库：lessons/cases 入库需你确认后运行 `python3 rules/apply_archive.py --bid " + BID + "`（幂等，双跑 no-op）。",
  ].join("\n"),
  { title: `归档提案报告 · ${BID}` },
);
const result: WorkflowReport = {
  conclusion: `${BID} 归档提案完成：教训 ${nLessons} 条、案例 ${nCases} 条，脱敏机检通过，产物落 ~/.bidmaster/bids/${BID}/archive/。确认采纳后由人工执行 apply_archive 入库。`,
  verified: [
    "supersession/evidence 完整性由落盘脚本逐条校验",
    "rules/desensitize.py 脱敏机检通过（身份证/手机号/证书编号三类红线）",
    "proposal.json 已按契约登记进 truth.db（status=proposed）",
  ],
  notCovered: [
    "apply_archive（教训/案例真正入 kb 与 lessons 表）——等人工确认后执行",
    "S8→S9 门禁的 proposal_confirmed 人工采纳位——本流水线不代办",
    "案例切片入库与时效复核——归 apply_archive 后的人工流程",
  ],
};
return result;