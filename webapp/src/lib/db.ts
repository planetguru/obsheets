import { DatabaseSync } from "node:sqlite";
import { mkdirSync } from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import type { PackSource } from "./schema";

export interface PackRow {
  id: string;
  title: string;
  creatorName: string;
  creatorEmail: string;
  createdAt: string;
  meetName: string;
  sessionNumber: number;
  sessionLabel: string;
  course: string;
  poolLengthM: number;
  entryCount: number;
  eventCount: number;
  discrepancies: string[];
}

export interface PackFull extends PackRow {
  sourceJson: PackSource;
  generatedHtml: string;
}

let db: DatabaseSync | null = null;

function getDb(): DatabaseSync {
  if (db) return db;
  const dir = path.join(process.cwd(), "data");
  mkdirSync(dir, { recursive: true });
  db = new DatabaseSync(path.join(dir, "obsheets.db"));
  db.exec(`
    CREATE TABLE IF NOT EXISTS packs (
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      creatorName TEXT NOT NULL,
      creatorEmail TEXT NOT NULL,
      createdAt TEXT NOT NULL,
      meetName TEXT NOT NULL,
      sessionNumber INTEGER NOT NULL,
      sessionLabel TEXT NOT NULL,
      course TEXT NOT NULL,
      poolLengthM INTEGER NOT NULL,
      entryCount INTEGER NOT NULL,
      eventCount INTEGER NOT NULL,
      discrepancies TEXT NOT NULL,
      sourceJson TEXT NOT NULL,
      generatedHtml TEXT NOT NULL
    );
  `);
  return db;
}

export function insertPack(p: Omit<PackFull, "id" | "createdAt">): string {
  const id = crypto.randomUUID();
  const createdAt = new Date().toISOString();
  getDb()
    .prepare(
      `INSERT INTO packs (id, title, creatorName, creatorEmail, createdAt, meetName,
         sessionNumber, sessionLabel, course, poolLengthM, entryCount, eventCount,
         discrepancies, sourceJson, generatedHtml)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
    .run(
      id,
      p.title,
      p.creatorName,
      p.creatorEmail,
      createdAt,
      p.meetName,
      p.sessionNumber,
      p.sessionLabel,
      p.course,
      p.poolLengthM,
      p.entryCount,
      p.eventCount,
      JSON.stringify(p.discrepancies),
      JSON.stringify(p.sourceJson),
      p.generatedHtml,
    );
  return id;
}

export function listPacks(): PackRow[] {
  const rows = getDb()
    .prepare(
      `SELECT id, title, creatorName, creatorEmail, createdAt, meetName, sessionNumber,
              sessionLabel, course, poolLengthM, entryCount, eventCount, discrepancies
       FROM packs ORDER BY createdAt DESC`,
    )
    .all() as Record<string, unknown>[];
  return rows.map((r) => ({
    ...(r as object),
    discrepancies: JSON.parse(r.discrepancies as string),
  })) as PackRow[];
}

export function getPack(id: string): PackFull | null {
  const r = getDb().prepare(`SELECT * FROM packs WHERE id = ?`).get(id) as
    | Record<string, unknown>
    | undefined;
  if (!r) return null;
  return {
    ...(r as object),
    discrepancies: JSON.parse(r.discrepancies as string),
    sourceJson: JSON.parse(r.sourceJson as string),
  } as PackFull;
}
