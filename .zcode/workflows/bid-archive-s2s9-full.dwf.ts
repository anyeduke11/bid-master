// ============ bid-archive-s2s9-full · 定制后程 S8→S9（DEV-0042 生成）============
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
      : `机检拦下：\n${feedback}\n修正后重出完整 proposal + lessons-draft。`);
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
      "pp.write_text(json.dumps(prop, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')",
      "(ws / 'lessons-draft.md').write_text(md, encoding='utf-8')",
      "reg = store.register_artifact(bid, 'proposal', str(pp), status='proposed', producer='bid-archivist')",
      "print(json.dumps({'ok': True, 'dir': str(ws), 'register': reg}, ensure_ascii=False))",
    ].join("\n"),
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
