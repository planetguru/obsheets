import { NextResponse } from "next/server";
import { getUser } from "@/lib/user";
import { extractDocuments, type UploadedDoc } from "@/lib/extract";
import { DOC_SLOTS } from "@/lib/slots";

export const maxDuration = 600; // extraction of large PDFs can take a while

export async function POST(req: Request) {
  const user = await getUser();
  if (!user) return NextResponse.json({ ok: false, error: "Not signed in" }, { status: 401 });

  try {
    const form = await req.formData();
    const docs: UploadedDoc[] = [];
    for (const slot of DOC_SLOTS) {
      const file = form.get(slot.key);
      if (file && file instanceof File && file.size > 0) {
        docs.push({
          slot: slot.key,
          filename: file.name,
          mediaType: file.type || "application/pdf",
          data: Buffer.from(await file.arrayBuffer()),
        });
      }
    }
    if (!docs.some((d) => d.slot === "entries")) {
      return NextResponse.json(
        { ok: false, error: "The confirmed entries report is required — it's the authoritative document." },
        { status: 400 },
      );
    }
    const { data, mock } = await extractDocuments(docs);
    return NextResponse.json({ ok: true, data, mock });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ ok: false, error: msg }, { status: 500 });
  }
}
