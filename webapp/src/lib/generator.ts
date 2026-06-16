// Deterministic sheet generator. Implements the standing rules exactly:
//   Rule 1 — splits: distance ÷ pool length boxes, cumulative labels,
//            no splits row for a single-length race.
//   Rule 2 — order: slowest first, NT at the very top,
//            tie-break surname then first name.
//   Events in numerical order; each event starts on a new page.
// The HTML/CSS template is the contract for "looks like the existing sheet" —
// only the data changes.
import type { EventEntry, PackSource, Swimmer } from "./schema";

const STROKE_NAMES: Record<string, string> = {
  Back: "Backstroke",
  Breast: "Breaststroke",
  Free: "Freestyle",
  Fly: "Butterfly",
  Medley: "IM",
  IM: "IM",
};

export function strokeDisplay(stroke: string): string {
  return STROKE_NAMES[stroke] ?? stroke;
}

export function escapeHtml(s: string): string {
  return s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function toSeconds(t: string): number {
  const trimmed = (t ?? "").trim();
  if (!trimmed || trimmed.toUpperCase() === "NT") return Infinity;
  const parts = trimmed.split(":");
  if (parts.length === 2) return parseInt(parts[0], 10) * 60 + parseFloat(parts[1]);
  const v = parseFloat(trimmed);
  return Number.isFinite(v) ? v : Infinity;
}

export function sortSwimmers(swimmers: Swimmer[]): Swimmer[] {
  // Slowest first, NT (Infinity) at the top; ties alphabetical surname, first.
  return [...swimmers].sort((a, b) => {
    const ta = toSeconds(a.entryTime);
    const tb = toSeconds(b.entryTime);
    if (ta !== tb) return tb - ta; // larger time first (Infinity handled: NT top)
    const s = a.surname.localeCompare(b.surname);
    if (s !== 0) return s;
    return a.first.localeCompare(b.first);
  });
}

export function splitCount(distanceM: number, poolLengthM: number): number {
  if (distanceM <= poolLengthM) return 0;
  return Math.floor(distanceM / poolLengthM);
}

const CSS = `<style>
  :root{--ink:#10243f; --accent:#0a558c; --line:#9fb2c6; --soft:#eef3f8;}
  *{box-sizing:border-box;}
  html,body{margin:0;padding:0;}
  body{font-family:"Helvetica Neue",Helvetica,Segoe UI,Roboto,sans-serif;
    color:var(--ink); background:#fff; line-height:1.25;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;}
  .page{max-width:760px; margin:0 auto; padding:22px 26px;}
  header.cover{border:2px solid var(--ink); border-radius:10px; padding:16px 20px;
    margin-bottom:18px; background:linear-gradient(180deg,#fff,var(--soft));}
  header.cover h1{margin:0; font-size:20px; letter-spacing:.5px;}
  header.cover .sub{margin-top:4px; font-size:14px; color:var(--accent); font-weight:700;}
  header.cover .meta{margin-top:8px; font-size:12px; color:#43566b;}
  section.event{break-before:page; page-break-before:always; margin-top:4px;}
  section.event:first-of-type{break-before:auto; page-break-before:auto;}
  .ehead{display:flex; align-items:baseline; gap:14px; flex-wrap:wrap;
    background:#fff; color:var(--accent); border:2px solid var(--accent);
    padding:8px 14px; border-radius:7px; margin-bottom:12px;}
  .ehead .enum{font-weight:800; font-size:16px; letter-spacing:.5px;}
  .ehead .etitle{font-weight:700; font-size:15px;}
  .ehead .emeta{margin-left:auto; font-size:12px; color:#5b6e84;}
  .swimmer{border:1.4px solid var(--line); border-radius:8px;
    padding:9px 12px 11px; margin-bottom:11px;
    break-inside:avoid; page-break-inside:avoid;}
  .srow{display:flex; align-items:center; gap:12px;}
  .name{font-weight:700; font-size:15px; flex:1; min-width:0;}
  .name .evtag{font-size:10px; color:#7488a0; font-weight:700; margin-right:7px;}
  .name .age{color:#5b6e84; font-weight:500; font-size:13px;}
  .field{display:flex; align-items:center; gap:6px;}
  .field label{font-size:10px; text-transform:uppercase; letter-spacing:.6px; color:#5b6e84;}
  .entry{min-width:62px; text-align:center; font-size:13px; font-weight:600;
    background:var(--soft); border:1px solid var(--line); border-radius:4px; padding:3px 6px;}
  .blank{width:78px; height:24px; border:1px solid var(--ink); border-radius:4px; background:#fff;}
  .blank.heat{width:48px;}
  .srow2{display:flex; align-items:flex-end; gap:10px; margin-top:9px;}
  .splabel{font-size:10px; text-transform:uppercase; letter-spacing:.6px;
    color:#5b6e84; white-space:nowrap; padding-bottom:3px;}
  .splits{display:flex; gap:6px; flex-wrap:wrap;}
  .split{display:flex; flex-direction:column; align-items:center; gap:2px;}
  .split .dist{font-size:9px; color:#7488a0;}
  .split .line{width:54px; height:26px; border:1px solid var(--ink); border-radius:4px; background:#fff;}
  .comments{margin-top:9px;}
  .comments label{font-size:10px; text-transform:uppercase; letter-spacing:.6px; color:#5b6e84;}
  .cbox{margin-top:3px; height:54px; border:1px solid var(--ink); border-radius:5px;
    background:#fff;
    background-image:repeating-linear-gradient(transparent,transparent 25px,#dde6ef 25px,#dde6ef 26px);}
  @page{size:A4 portrait; margin:12mm;}
  @media print{ .page{max-width:none; padding:0;} }
</style>`;

function swimmerBlock(sw: Swimmer, ev: EventEntry, poolLengthM: number): string {
  const n = splitCount(ev.distanceM, poolLengthM);
  let splitsRow = "";
  if (n > 0) {
    const boxes = Array.from({ length: n }, (_, i) =>
      `<div class="split"><div class="dist">${(i + 1) * poolLengthM}</div><div class="line"></div></div>`,
    ).join("");
    splitsRow = `
    <div class="srow2">
      <div class="splabel">${poolLengthM}m splits</div>
      <div class="splits">${boxes}</div>
    </div>`;
  }
  const age = sw.age != null ? ` <span class="age">(${sw.age})</span>` : "";
  const entry = (sw.entryTime ?? "").trim() || "NT";
  return `<div class="swimmer">
    <div class="srow">
      <div class="name"><span class="evtag">#${ev.number}</span>${escapeHtml(sw.first)} ${escapeHtml(sw.surname)}${age}</div>
      <div class="field"><label>Heat</label><div class="blank heat"></div></div>
      <div class="field"><label>Entry</label><div class="entry">${escapeHtml(entry)}</div></div>
      <div class="field"><label>Time</label><div class="blank"></div></div>
    </div>${splitsRow}
    <div class="comments"><label>Coach&#8217;s comments</label><div class="cbox"></div></div>
  </div>`;
}

function eventSection(ev: EventEntry, poolLengthM: number): string {
  const n = splitCount(ev.distanceM, poolLengthM);
  const count = ev.swimmers.length;
  const splitsTag = n > 0 ? ` &middot; ${n} &times; ${poolLengthM}m` : "";
  const blocks = sortSwimmers(ev.swimmers)
    .map((sw) => swimmerBlock(sw, ev, poolLengthM))
    .join("\n");
  return `<section class="event">
  <div class="ehead">
    <div class="enum">Event ${ev.number}</div>
    <div class="etitle">${escapeHtml(ev.gender)} &middot; ${ev.distanceM}m ${escapeHtml(strokeDisplay(ev.stroke))}</div>
    <div class="emeta">${count} swimmer${count !== 1 ? "s" : ""}${splitsTag}</div>
  </div>
${blocks}
</section>`;
}

export interface GenerateResult {
  html: string;
  entryCount: number;
  eventCount: number;
}

export function generateSheet(src: PackSource): GenerateResult {
  const pool = src.poolLengthM;
  const events = [...src.events].sort((a, b) => a.number - b.number);
  const entryCount = events.reduce((acc, e) => acc + e.swimmers.length, 0);
  const evNums = events.map((e) => e.number);
  const evRange = evNums.length ? `Events ${Math.min(...evNums)}–${Math.max(...evNums)}` : "";
  const courseLabel = src.meet.course === "long" ? `Long Course (${pool}m)` : `Short Course (${pool}m)`;
  const hasSplits = events.some((e) => splitCount(e.distanceM, pool) > 0);
  const splitsNote = hasSplits ? ` &middot; splits every ${pool}m` : "";

  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Session ${src.sessionNumber} &ndash; ${escapeHtml(src.meet.club)}</title>
${CSS}
</head>
<body>
<div class="page">
<header class="cover">
  <h1>${escapeHtml(src.meet.name)} &mdash; Coach Recording Sheet</h1>
  <div class="sub">Session ${src.sessionNumber} &middot; ${escapeHtml(src.sessionLabel)} &middot; ${escapeHtml(src.meet.club)}</div>
  <div class="meta">${courseLabel} &middot; ${escapeHtml(src.meet.venue)} &middot; ${evRange}${splitsNote} &middot;
    entry times shown; write heat, achieved time, splits &amp; comments.</div>
</header>
${events.map((ev) => eventSection(ev, pool)).join("\n")}
</div>
</body>
</html>`;
  return { html, entryCount, eventCount: events.length };
}

// Discrepancy rule: never change the sheet — surface notices only.
export function computeDiscrepancies(src: PackSource): string[] {
  if (!src.attendance?.provided) return [];
  const sessionAtt = src.attendance.bySession.find((s) => s.timelineTag === src.timelineTag);
  if (!sessionAtt) return [];
  const norm = (s: string) => s.trim().toLowerCase().replace(/\s+/g, " ");
  const attending = new Set(sessionAtt.swimmers.map(norm));
  const entered = new Map<string, string>(); // normalized -> display
  for (const ev of src.events) {
    for (const sw of ev.swimmers) {
      const display = `${sw.first} ${sw.surname}`;
      entered.set(norm(display), display);
    }
  }
  const out: string[] = [];
  for (const [key, display] of entered) {
    if (!attending.has(key)) {
      out.push(
        `${display} is entered in Session ${src.sessionNumber} events but is not on the TM attendance list.`,
      );
    }
  }
  for (const name of sessionAtt.swimmers) {
    if (!entered.has(norm(name))) {
      out.push(
        `${name.trim()} is on the TM attendance list for Session ${src.sessionNumber} but has no entries in this session.`,
      );
    }
  }
  return out;
}
