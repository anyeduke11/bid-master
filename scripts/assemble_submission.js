#!/usr/bin/env node
/**
 * assemble_submission.js · 磋商响应文件（技术部分）docx 装配器（产品化自 DEV-0040 实战版）
 * 用法：node scripts/assemble_submission.js <bid_dir> [output_name]
 *   <bid_dir>     ~/.bidmaster/bids/<bid>（绝对路径、~ 开头，或相对仓库根）
 * 读取 draft/ch-*.md（字典序）→ 三节结构 docx（扉页 / 目录 / 正文，正文页码从 1）
 * 依赖：docx（自动尝试 repo/node_modules 与 ~/node_modules）
 */
const os = require("os");
const path = require("path");
module.paths.push(path.join(os.homedir(), "node_modules"));
module.paths.push(path.join(process.cwd(), "node_modules"));
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        PageBreak, Footer, PageNumber, NumberFormat, SectionType,
        AlignmentType, HeadingLevel, WidthType, BorderStyle, ShadingType, TableOfContents } = require("docx");
const fs = require("fs");

// 路径边界（Mimosa 建议）：仅允许 ~/.bidmaster/bids/ 之下的 bid 目录
const BIDS_ROOT = path.join(os.homedir(), ".bidmaster", "bids");
const BIDS_DIR = path.resolve(process.argv[2] ? process.argv[2].replace(/^~/, os.homedir()) : ".");
if (BIDS_DIR !== BIDS_ROOT && !BIDS_DIR.startsWith(BIDS_ROOT + path.sep)) {
  console.error("❌ 非法目录：仅允许 ~/.bidmaster/bids/ 之下的 bid 目录，收到:", BIDS_DIR);
  process.exit(1);
}
const OUT_NAME = process.argv[3] || "磋商响应文件（技术部分）.docx";
if (!/^[\w\u4e00-\u9fa5（）().\-]+$/.test(OUT_NAME)) {
  console.error("❌ 非法输出文件名（仅允许中英文/数字/点/横线/括号）:", OUT_NAME);
  process.exit(1);
}
const OUT = path.join(BIDS_DIR, "submission", OUT_NAME);
const CN = ["一","二","三","四","五","六","七","八","九","十"];
const FONT_BODY = { ascii: "Times New Roman", eastAsia: "SimSun" };
const FONT_HEAD = { ascii: "Times New Roman", eastAsia: "SimHei" };

function inlineRuns(text, base = {}) {
  const runs = [];
  String(text).split(/\*\*(.+?)\*\*/g).forEach((p, i) => {
    if (!p) return;
    runs.push(new TextRun({ text: p, bold: i % 2 === 1 ? true : base.bold, size: base.size || 24, font: base.font || FONT_BODY, color: base.color || "000000" }));
  });
  if (!runs.length) runs.push(new TextRun({ text: "", size: base.size || 24 }));
  return runs;
}
function mdTable(rows) {
  const mk = (cells, isHead) => new TableRow({
    tableHeader: isHead === true, cantSplit: true,
    children: cells.map(c => new TableCell({
      children: [new Paragraph({ spacing: { line: 360 }, children: inlineRuns(c, { size: 21, bold: isHead === true }) })],
      shading: isHead ? { type: ShadingType.CLEAR, fill: "EDF1F6" } : undefined,
      margins: { top: 60, bottom: 60, left: 110, right: 110 },
    })),
  });
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: "404B5A" }, bottom: { style: BorderStyle.SINGLE, size: 4, color: "404B5A" },
      left: { style: BorderStyle.SINGLE, size: 2, color: "9AA6B2" }, right: { style: BorderStyle.SINGLE, size: 2, color: "9AA6B2" },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: "C8CFD8" }, insideVertical: { style: BorderStyle.SINGLE, size: 2, color: "D8DDE4" },
    },
    rows: [mk(rows[0], true), ...rows.slice(1).map(r => mk(r, false))],
  });
}
function parseMd(text) {
  const out = [];
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const t = lines[i].trim();
    if (!t || t === "---" || t.startsWith("<!--") || t.startsWith("{\"status\"")) continue;
    if (t.startsWith("### ")) out.push(new Paragraph({ heading: HeadingLevel.HEADING_3, spacing: { before: 200, after: 100, line: 360 }, children: [new TextRun({ text: t.slice(4), bold: true, font: FONT_HEAD })] }));
    else if (t.startsWith("## ")) out.push(new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 260, after: 120, line: 360 }, children: [new TextRun({ text: t.slice(3), bold: true, font: FONT_HEAD })] }));
    else if (t.startsWith("# ")) continue; // 原 H1 由装配器统一生成（防目录重复条目）
    else if (t.startsWith(">")) out.push(new Paragraph({
      spacing: { before: 120, after: 120, line: 360 }, indent: { left: 240 },
      border: { left: { style: BorderStyle.SINGLE, size: 24, color: "B45309", space: 8 } },
      shading: { type: ShadingType.CLEAR, fill: "FFF8EC" },
      children: inlineRuns(t.replace(/^>\s?/, ""), { color: "7C4A03" }),
    }));
    else if (t.startsWith("|")) {
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const cells = lines[i].trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
        if (!cells.every(c => /^:?-{2,}:?$/.test(c))) rows.push(cells);
        i++;
      }
      if (rows.length) out.push(mdTable(rows));
      continue;
    }
    else if (t.startsWith("- ")) out.push(new Paragraph({ bullet: { level: 0 }, spacing: { line: 360 }, children: inlineRuns(t.slice(2)) }));
    else out.push(new Paragraph({ alignment: AlignmentType.JUSTIFIED, indent: { firstLine: 480 }, spacing: { line: 360 }, children: inlineRuns(t) }));
  }
  return out;
}

const draftDir = path.join(BIDS_DIR, "draft");
const chapters = fs.readdirSync(draftDir).filter(f => /^ch-.+\.md$/.test(f)).sort();
if (!chapters.length) { console.error("❌ draft/ 下无 ch-*.md"); process.exit(1); }
const body = [];
chapters.forEach((ch, idx) => {
  const raw = fs.readFileSync(path.join(draftDir, ch), "utf-8");
  const m = raw.split("\n").find(l => l.startsWith("# "));
  const clean = (m ? m.slice(2) : ch).replace(/^第[A-J一二三四五六七八九十]+章\s*/, "").trim();
  body.push(new Paragraph({
    heading: HeadingLevel.HEADING_1, pageBreakBefore: idx > 0,
    spacing: { before: 320, after: 200, line: 360 },
    children: [new TextRun({ text: `第${CN[idx]}章 ${clean}`, bold: true, font: FONT_HEAD })],
  }));
  body.push(...parseMd(raw));
});
const tp = (text, size, opts = {}) => new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { before: opts.before || 0, after: opts.after || 0, line: 360 },
  children: [new TextRun({ text, bold: opts.bold !== false, size, font: FONT_HEAD })],
});
const cover = [
  tp(" ", 24, { before: 1800 }),
  tp("2027年度安全服务采购项目", 44, { after: 200 }),
  tp("竞争性磋商响应文件", 52, { after: 160 }),
  tp("（技术部分）", 30, { after: 2200 }),
  tp("项目编号：〔待填〕", 28, { after: 120 }),
  tp("采购人：〔待填〕", 28, { after: 2200 }),
  tp("响应人：〔待盖章〕", 28, { after: 120 }),
  tp("日期：〔待填〕", 28, {}),
];
const tocChildren = [
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 480, after: 360 }, children: [new TextRun({ text: "目  录", bold: true, size: 32, font: FONT_HEAD })] }),
  new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-2" }),
  new Paragraph({ spacing: { before: 200 }, children: [new TextRun({ text: "注：本目录由域代码生成，编辑后请右键目录选择“更新域”以刷新页码。", italics: true, size: 18, color: "888888" })] }),
  new Paragraph({ children: [new PageBreak()] }),
];
const footer = () => new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: [PageNumber.CURRENT], size: 18, font: FONT_BODY })] })] });
const pg = { size: { width: 11906, height: 16838 }, margin: { top: 1440, bottom: 1440, left: 1701, right: 1417 } };
const doc = new Document({
  styles: { default: { document: { run: { font: FONT_BODY, size: 24, color: "000000" }, paragraph: { spacing: { line: 360 } } } } },
  features: { updateFields: true },
  sections: [
    { properties: { page: pg }, children: cover },
    { properties: { type: SectionType.NEXT_PAGE, page: pg }, children: tocChildren },
    { properties: { type: SectionType.NEXT_PAGE, page: { ...pg, pageNumbers: { start: 1, formatType: NumberFormat.DECIMAL } } }, footers: { default: footer() }, children: body },
  ],
});
fs.mkdirSync(path.join(BIDS_DIR, "submission"), { recursive: true });
Packer.toBuffer(doc).then(buf => { fs.writeFileSync(OUT, buf); console.log("written:", OUT, buf.length, "bytes,", chapters.length, "章"); });
