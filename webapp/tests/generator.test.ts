import { test } from "node:test";
import assert from "node:assert/strict";
import {
  toSeconds,
  sortSwimmers,
  splitCount,
  generateSheet,
  computeDiscrepancies,
  strokeDisplay,
} from "../src/lib/generator.ts";
import type { PackSource } from "../src/lib/schema.ts";

// ── Rule 1: splits ────────────────────────────────────────────────────────────

test("splits: race of exactly one pool length has no splits row", () => {
  assert.equal(splitCount(50, 50), 0); // 50m LC
  assert.equal(splitCount(25, 25), 0); // 25m SC
});

test("splits: long course examples from the spec", () => {
  assert.equal(splitCount(100, 50), 2);
  assert.equal(splitCount(200, 50), 4);
  assert.equal(splitCount(400, 50), 8);
});

test("splits: short course examples from the spec", () => {
  assert.equal(splitCount(50, 25), 2);
  assert.equal(splitCount(100, 25), 4);
  assert.equal(splitCount(400, 25), 16);
});

// ── Rule 2: ordering ──────────────────────────────────────────────────────────

const sw = (first: string, surname: string, entryTime: string) => ({
  first,
  surname,
  age: 12,
  entryTime,
});

test("order: slowest first, fastest at the bottom", () => {
  const sorted = sortSwimmers([sw("A", "Fast", "30.00"), sw("B", "Slow", "50.00"), sw("C", "Mid", "40.00")]);
  assert.deepEqual(
    sorted.map((s) => s.surname),
    ["Slow", "Mid", "Fast"],
  );
});

test("order: NT counts as slowest and goes to the very top", () => {
  const sorted = sortSwimmers([sw("A", "Fast", "30.00"), sw("B", "None", "NT"), sw("C", "Slow", "5:00.00")]);
  assert.equal(sorted[0].surname, "None");
  assert.equal(sorted[1].surname, "Slow");
});

test("order: ties broken by surname then first name, alphabetical", () => {
  const sorted = sortSwimmers([
    sw("Tara", "Wells", "NT"),
    sw("Mark", "Wells", "NT"),
    sw("Anna", "Avon", "NT"),
  ]);
  assert.deepEqual(
    sorted.map((s) => `${s.first} ${s.surname}`),
    ["Anna Avon", "Mark Wells", "Tara Wells"],
  );
});

test("toSeconds parses minute and second formats", () => {
  assert.equal(toSeconds("1:30.50"), 90.5);
  assert.equal(toSeconds("36.50"), 36.5);
  assert.equal(toSeconds("NT"), Infinity);
  assert.equal(toSeconds(""), Infinity);
});

// ── Generation ────────────────────────────────────────────────────────────────

const SOURCE: PackSource = {
  meet: {
    name: "City of Wells Open Meet 2026",
    venue: "Millfield School, Street, Somerset",
    dates: "30-31 May 2026",
    course: "long",
    club: "Bridgwater ASC",
  },
  poolLengthM: 50,
  sessionNumber: 3,
  sessionLabel: "Sunday 31 May AM",
  timelineTag: "t3",
  events: [
    {
      number: 18,
      timelineTag: "t3",
      gender: "Girls",
      distanceM: 100,
      stroke: "Back",
      swimmers: [
        sw("Bella", "Brook", "1:40.20"),
        sw("Cara", "Crane", "1:47.90"),
        sw("Dana", "Dale", "1:29.60"),
      ],
    },
    {
      number: 16,
      timelineTag: "t3",
      gender: "Girls",
      distanceM: 400,
      stroke: "IM",
      swimmers: [sw("Ella", "East", "6:48.80")],
    },
    {
      number: 21,
      timelineTag: "t3",
      gender: "Boys",
      distanceM: 50,
      stroke: "Free",
      swimmers: [sw("Finn", "Frost", "33.60")],
    },
  ],
  attendance: {
    provided: true,
    // Cara Crane is entered but absent from this list; Ghost Swimmer is the reverse.
    bySession: [{ timelineTag: "t3", swimmers: ["Bella Brook", "Dana Dale", "Ella East", "Finn Frost", "Ghost Swimmer"] }],
  },
};

test("generate: events appear in numerical order regardless of input order", () => {
  const { html } = generateSheet(SOURCE);
  const e16 = html.indexOf("Event 16");
  const e18 = html.indexOf("Event 18");
  const e21 = html.indexOf("Event 21");
  assert.ok(e16 > -1 && e16 < e18 && e18 < e21);
});

test("generate: entry count matches and swimmer blocks are placed", () => {
  const { html, entryCount, eventCount } = generateSheet(SOURCE);
  assert.equal(entryCount, 5);
  assert.equal(eventCount, 3);
  assert.equal((html.match(/class="swimmer"/g) ?? []).length, 5);
});

test("generate: 400m LC event has 8 cumulative split labels, 50m LC has none", () => {
  const { html } = generateSheet(SOURCE);
  const ev16 = html.slice(html.indexOf("Event 16"), html.indexOf("Event 18"));
  const dists = [...ev16.matchAll(/<div class="dist">(\d+)<\/div>/g)].map((m) => m[1]);
  assert.deepEqual(dists, ["50", "100", "150", "200", "250", "300", "350", "400"]);
  const ev21 = html.slice(html.indexOf("Event 21"));
  assert.ok(!ev21.includes('class="srow2"'), "single-length race must have no splits row");
  assert.ok(ev21.includes("1 swimmer"), "meta should not pluralise one swimmer");
  assert.ok(!ev21.includes("&times;"), "single-length race must not advertise splits in the header");
});

test("generate: swimmers within an event run slowest-first in the HTML", () => {
  const { html } = generateSheet(SOURCE);
  const ev18 = html.slice(html.indexOf("Event 18"), html.indexOf("Event 21"));
  const names = [...ev18.matchAll(/<\/span>([A-Za-z]+ [A-Za-z]+)/g)].map((m) => m[1]);
  assert.deepEqual(names, ["Cara Crane", "Bella Brook", "Dana Dale"]);
});

test("generate: entry times are pre-filled; heat and time boxes are blank", () => {
  const { html } = generateSheet(SOURCE);
  assert.ok(html.includes('<div class="entry">1:29.60</div>'));
  assert.ok(html.includes('<div class="blank heat"></div>'));
  assert.ok(html.includes('<div class="blank"></div>'));
});

test("generate: template contract — outlined headers, page breaks, A4 portrait", () => {
  const { html } = generateSheet(SOURCE);
  assert.ok(html.includes("break-before:page"));
  assert.ok(html.includes("break-inside:avoid"));
  assert.ok(html.includes("size:A4 portrait"));
  assert.ok(html.includes("border:2px solid var(--accent)"));
});

test("strokeDisplay maps short names", () => {
  assert.equal(strokeDisplay("Back"), "Backstroke");
  assert.equal(strokeDisplay("IM"), "IM");
  assert.equal(strokeDisplay("Medley"), "IM");
});

// ── Discrepancies (§5.5) ──────────────────────────────────────────────────────

test("discrepancies: entered-but-absent and attending-but-not-entered are flagged", () => {
  const d = computeDiscrepancies(SOURCE);
  assert.equal(d.length, 2);
  assert.ok(d.some((x) => x.includes("Cara Crane") && x.includes("not on the TM attendance list")));
  assert.ok(d.some((x) => x.includes("Ghost Swimmer") && x.includes("no entries")));
});

test("discrepancies: none when attendance not provided", () => {
  const d = computeDiscrepancies({ ...SOURCE, attendance: { provided: false, bySession: [] } });
  assert.deepEqual(d, []);
});
