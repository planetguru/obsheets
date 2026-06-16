import { NextResponse } from "next/server";
import { getUser } from "@/lib/user";
import { insertPack } from "@/lib/db";
import { generateSheet, computeDiscrepancies } from "@/lib/generator";
import type { PackSource } from "@/lib/schema";

export async function POST(req: Request) {
  const user = await getUser();
  if (!user) return NextResponse.json({ ok: false, error: "Not signed in" }, { status: 401 });

  try {
    const body = (await req.json()) as { title?: string; source: PackSource };
    const src = body.source;
    if (!src?.events?.length) {
      return NextResponse.json(
        { ok: false, error: "No events in the selected session — nothing to generate." },
        { status: 400 },
      );
    }

    const { html, entryCount, eventCount } = generateSheet(src);

    // Verification (§5.6): entries placed on the sheet must match the reviewed
    // data. Counted independently from the generated HTML so a generator bug
    // can't pass its own check.
    const placed = (html.match(/class="swimmer"/g) ?? []).length;
    const sourceCount = src.events.reduce((acc, e) => acc + e.swimmers.length, 0);
    if (placed !== sourceCount || entryCount !== sourceCount) {
      return NextResponse.json(
        {
          ok: false,
          error: `Entry count check FAILED: ${sourceCount} entries in the reviewed data but ${placed} placed on the sheet. The pack was not saved — please report this.`,
        },
        { status: 500 },
      );
    }

    const discrepancies = computeDiscrepancies(src);
    const title =
      (body.title ?? "").trim() ||
      `${src.meet.name} — Session ${src.sessionNumber}`;

    const id = insertPack({
      title,
      creatorName: user.name,
      creatorEmail: user.email,
      meetName: src.meet.name,
      sessionNumber: src.sessionNumber,
      sessionLabel: src.sessionLabel,
      course: src.meet.course,
      poolLengthM: src.poolLengthM,
      entryCount,
      eventCount,
      discrepancies,
      sourceJson: src,
      generatedHtml: html,
    });
    return NextResponse.json({ ok: true, id, entryCount, eventCount, discrepancies });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ ok: false, error: msg }, { status: 500 });
  }
}
