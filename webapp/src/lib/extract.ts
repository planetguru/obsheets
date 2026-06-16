// LLM document extraction: uploaded gala documents → Extraction JSON.
// The LLM only extracts. All generation rules (splits, ordering, sessions,
// discrepancies) are applied by deterministic code in generator.ts.
import Anthropic from "@anthropic-ai/sdk";
import { readFileSync } from "node:fs";
import path from "node:path";
import { EXTRACTION_JSON_SCHEMA, type Extraction } from "./schema";
import { DOC_SLOTS } from "./slots";

export interface UploadedDoc {
  slot: string; // "meetPack" | "entries" | "committed" | "attendance"
  filename: string;
  mediaType: string;
  data: Buffer;
}

const SYSTEM_PROMPT = `You extract structured data from swimming gala documents for Bridgwater ASC.
You will receive up to four documents, each preceded by a label naming which document it is.

Extract into the provided JSON schema. Rules:

- The CONFIRMED ENTRIES REPORT is authoritative for who is entered, which events
  (by number), swimmer ages, and entry times. If it disagrees with the committed
  athletes export on an entry time or event, the entries report wins.
- The COMMITTED ATHLETES export is authoritative for which session each event
  belongs to: tags like (d2/t3) mean day 2, timeline 3 — set the event's
  timelineTag to "t3". If no committed-athletes document is provided, infer
  timeline tags however the available documents allow and say so in extractionNotes.
- The MEET PACK provides meet name, venue, dates, and course. Long course = 50m
  pool, short course = 25m. If absent, infer course from time suffixes
  (e.g. "1:29.60L" = long) and note the inference.
- Entry times: keep exactly as printed ("1:29.60", "36.50") or "NT" for no time.
  Strip any trailing course letter (L/S) from times.
- Ages: use the swimmer's actual age from the entries report when present
  (e.g. "Age: 14"); null if no age is given anywhere.
- sessions: list every distinct session you can detect, with its timeline tag,
  day and AM/PM where determinable.
- attendance: if a TM attendance list is provided, list the swimmers per session
  exactly as named ("First Surname"); otherwise provided=false.
- Do NOT compute split counts, do NOT order swimmers, do NOT resolve
  entered-vs-attending differences — downstream code does that.
- Anything ambiguous (course unclear, session labels that don't match t1-t4,
  duplicate names, unreadable rows) goes in extractionNotes so the coach can
  review it. Never guess silently.`;

type ContentBlock =
  | { type: "text"; text: string }
  | { type: "document"; source: { type: "base64"; media_type: "application/pdf"; data: string } }
  | {
      type: "image";
      source: {
        type: "base64";
        media_type: "image/jpeg" | "image/png" | "image/gif" | "image/webp";
        data: string;
      };
    };

const IMAGE_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp"];

function docBlocks(doc: UploadedDoc): ContentBlock[] {
  const slot = DOC_SLOTS.find((s) => s.key === doc.slot);
  const label: ContentBlock = {
    type: "text",
    text: `--- Document: ${slot?.label ?? doc.slot} (${doc.filename}) ---`,
  };
  if (doc.mediaType === "application/pdf") {
    return [
      label,
      {
        type: "document",
        source: { type: "base64", media_type: "application/pdf", data: doc.data.toString("base64") },
      },
    ];
  }
  if (IMAGE_TYPES.includes(doc.mediaType)) {
    return [
      label,
      {
        type: "image",
        source: {
          type: "base64",
          media_type: doc.mediaType as "image/jpeg" | "image/png" | "image/gif" | "image/webp",
          data: doc.data.toString("base64"),
        },
      },
    ];
  }
  throw new Error(`Unsupported file type ${doc.mediaType} for ${doc.filename} — upload a PDF or image.`);
}

export function isMockMode(): boolean {
  return process.env.EXTRACT_MOCK === "1" || !process.env.ANTHROPIC_API_KEY;
}

export async function extractDocuments(docs: UploadedDoc[]): Promise<{ data: Extraction; mock: boolean }> {
  if (isMockMode()) {
    const fixture = readFileSync(path.join(process.cwd(), "fixtures", "wells-extraction.json"), "utf-8");
    return { data: JSON.parse(fixture) as Extraction, mock: true };
  }

  const client = new Anthropic();
  const content: ContentBlock[] = [
    ...docs.flatMap(docBlocks),
    {
      type: "text",
      text: "Extract the structured data from these documents per your instructions.",
    },
  ];

  let message;
  try {
    // Long documents in, sizeable JSON out — stream to avoid HTTP timeouts.
    const stream = client.messages.stream({
      model: "claude-opus-4-8",
      max_tokens: 64000,
      thinking: { type: "adaptive" },
      system: SYSTEM_PROMPT,
      output_config: { format: { type: "json_schema", schema: EXTRACTION_JSON_SCHEMA } },
      messages: [{ role: "user", content }],
    });
    message = await stream.finalMessage();
  } catch (err) {
    throw new Error(friendlyApiError(err));
  }

  if (message.stop_reason === "refusal") {
    throw new Error("The extraction service declined this request — please check the documents and try again.");
  }
  if (message.stop_reason === "max_tokens") {
    throw new Error("The documents are too large to read in one pass — try uploading fewer pages, or split the meet pack.");
  }
  const text = message.content
    .filter((b): b is Anthropic.TextBlock => b.type === "text")
    .map((b) => b.text)
    .join("");
  try {
    return { data: JSON.parse(text) as Extraction, mock: false };
  } catch {
    throw new Error("The reading service returned an unexpected result. Please try again.");
  }
}

// Turn raw Anthropic SDK errors into plain English for a non-technical coach.
function friendlyApiError(err: unknown): string {
  if (err instanceof Anthropic.AuthenticationError) {
    return "Your Claude API key looks invalid. Check the ANTHROPIC_API_KEY value in webapp/.env.local (it should start with 'sk-ant-') and restart the app.";
  }
  if (err instanceof Anthropic.PermissionDeniedError) {
    return "Your Claude API key was rejected — it may be disabled, or your account may need billing/credit added at platform.claude.com.";
  }
  if (err instanceof Anthropic.RateLimitError) {
    return "Claude is busy right now (rate limit). Wait a minute and try again.";
  }
  if (err instanceof Anthropic.APIError) {
    if (err.status === 400 && /credit|billing|balance/i.test(err.message)) {
      return "Your Claude account is out of credit. Add credit at platform.claude.com → Billing, then try again.";
    }
    return `The reading service had a problem (${err.status}): ${err.message}`;
  }
  return err instanceof Error ? err.message : String(err);
}
