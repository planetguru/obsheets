"use client";

import { useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { DOC_SLOTS, type SlotKey } from "@/lib/slots";
import { computeDiscrepancies, splitCount, sortSwimmers } from "@/lib/generator";
import type { Extraction, EventEntry, PackSource } from "@/lib/schema";

const STEPS = ["Upload", "Extract", "Session", "Review", "Generate"];
const DEFAULT_MAPPING: Record<string, number> = { t1: 1, t2: 2, t3: 3, t4: 4 };

export default function Wizard() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [error, setError] = useState("");
  const [files, setFiles] = useState<Partial<Record<SlotKey, File>>>({});
  const [extraction, setExtraction] = useState<Extraction | null>(null);
  const [mock, setMock] = useState(false);
  const [mapping, setMapping] = useState<Record<string, number>>(DEFAULT_MAPPING);
  const [sessionTag, setSessionTag] = useState<string>("");
  const [events, setEvents] = useState<EventEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const inputRefs = useRef<Partial<Record<SlotKey, HTMLInputElement | null>>>({});

  // ── Step 1: upload ──────────────────────────────────────────────────────────
  function setFile(key: SlotKey, file: File | undefined) {
    setFiles((f) => ({ ...f, [key]: file }));
  }

  async function runExtraction() {
    setError("");
    if (!files.entries) {
      setError("Please add the confirmed entries report — it's the one required document.");
      return;
    }
    setStep(1);
    setBusy(true);
    try {
      const form = new FormData();
      for (const slot of DOC_SLOTS) {
        const f = files[slot.key];
        if (f) form.append(slot.key, f);
      }
      const resp = await fetch("/api/extract", { method: "POST", body: form });
      const json = await resp.json();
      if (!json.ok) throw new Error(json.error);
      setExtraction(json.data as Extraction);
      setMock(Boolean(json.mock));
      // Seed the mapping with any tags the documents revealed
      const tags = new Set<string>([
        ...(json.data as Extraction).sessions.map((s) => s.timelineTag),
        ...(json.data as Extraction).events.map((e) => e.timelineTag),
      ]);
      const m: Record<string, number> = {};
      [...tags].sort().forEach((t, i) => {
        m[t] = DEFAULT_MAPPING[t] ?? i + 1;
      });
      setMapping(m);
      setStep(2);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStep(0);
    } finally {
      setBusy(false);
    }
  }

  // ── Step 3: session pick ────────────────────────────────────────────────────
  const sessionTags = useMemo(() => {
    if (!extraction) return [];
    const tags = new Set(extraction.events.map((e) => e.timelineTag));
    return [...tags].sort((a, b) => (mapping[a] ?? 99) - (mapping[b] ?? 99));
  }, [extraction, mapping]);

  const mappingLooksOff = useMemo(
    () => sessionTags.some((t) => DEFAULT_MAPPING[t] === undefined),
    [sessionTags],
  );

  function pickSession(tag: string) {
    if (!extraction) return;
    setSessionTag(tag);
    // Deep-copy the session's events so review edits don't mutate the extraction
    setEvents(
      structuredClone(extraction.events.filter((e) => e.timelineTag === tag)).sort(
        (a, b) => a.number - b.number,
      ),
    );
    setStep(3);
  }

  // ── Step 4: review ──────────────────────────────────────────────────────────
  const [meet, setMeet] = useState({ name: "", venue: "", dates: "", course: "long", club: "Bridgwater ASC" });
  function enterReview(tag: string) {
    if (extraction) {
      setMeet({ ...extraction.meet });
    }
    pickSession(tag);
  }

  function updateSwimmer(evIdx: number, swIdx: number, field: string, value: string) {
    setEvents((evs) => {
      const next = structuredClone(evs);
      const sw = next[evIdx].swimmers[swIdx] as unknown as Record<string, unknown>;
      if (field === "age") sw.age = value === "" ? null : parseInt(value, 10) || null;
      else sw[field] = value;
      return next;
    });
  }

  function removeSwimmer(evIdx: number, swIdx: number) {
    setEvents((evs) => {
      const next = structuredClone(evs);
      next[evIdx].swimmers.splice(swIdx, 1);
      return next;
    });
  }

  function addSwimmer(evIdx: number) {
    setEvents((evs) => {
      const next = structuredClone(evs);
      next[evIdx].swimmers.push({ first: "", surname: "", age: null, entryTime: "NT" });
      return next;
    });
  }

  const sessionNumber = mapping[sessionTag] ?? 0;
  const poolLengthM = meet.course === "long" ? 50 : 25;
  const entryCount = events.reduce((acc, e) => acc + e.swimmers.length, 0);

  const sessionInfo = extraction?.sessions.find((s) => s.timelineTag === sessionTag);
  const sessionLabel = sessionInfo
    ? `${sessionInfo.day}${sessionInfo.ampm ? " " + sessionInfo.ampm : ""}`.trim() || `Session ${sessionNumber}`
    : `Session ${sessionNumber}`;

  const source: PackSource = {
    meet: { ...meet, course: meet.course as "long" | "short" },
    poolLengthM,
    sessionNumber,
    sessionLabel,
    timelineTag: sessionTag,
    events,
    attendance: extraction?.attendance ?? { provided: false, bySession: [] },
  };

  const discrepancies = useMemo(() => computeDiscrepancies(source), [source]);

  // ── Step 5: generate ────────────────────────────────────────────────────────
  async function generate() {
    setError("");
    setBusy(true);
    setStep(4);
    try {
      const resp = await fetch("/api/packs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source }),
      });
      const json = await resp.json();
      if (!json.ok) throw new Error(json.error);
      router.push(`/packs/${json.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStep(3);
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>New observation pack</h1>
      <div className="steps">
        {STEPS.map((s, i) => (
          <div key={s} className={`step ${i === step ? "on" : i < step ? "done" : ""}`}>
            {i + 1} · {s}
          </div>
        ))}
      </div>
      {error ? <div className="banner err">Something went wrong: {error}</div> : null}

      {step === 0 && (
        <div className="card">
          <h2>Upload the gala documents</h2>
          <p className="lede" style={{ marginBottom: 4 }}>
            Drop each document onto its slot (or click to choose). Only the entries report
            is required — add the others when the gala provides them.
          </p>
          {DOC_SLOTS.map((slot) => {
            const file = files[slot.key];
            return (
              <div
                key={slot.key}
                className={`slot ${file ? "filled" : ""}`}
                onClick={() => inputRefs.current[slot.key]?.click()}
                onDragOver={(e) => {
                  e.preventDefault();
                  e.currentTarget.classList.add("hover");
                }}
                onDragLeave={(e) => e.currentTarget.classList.remove("hover")}
                onDrop={(e) => {
                  e.preventDefault();
                  e.currentTarget.classList.remove("hover");
                  const f = e.dataTransfer.files?.[0];
                  if (f) setFile(slot.key, f);
                }}
              >
                <div className="slabel">
                  {slot.label} {slot.required ? <span className="req">*</span> : null}
                </div>
                <div className="ssub">
                  {slot.sublabel} — {slot.purpose}
                </div>
                {file ? <div className="sfile">✓ {file.name}</div> : null}
                <input
                  ref={(el) => {
                    inputRefs.current[slot.key] = el;
                  }}
                  type="file"
                  accept=".pdf,.html,.htm,image/*,application/pdf"
                  style={{ display: "none" }}
                  onChange={(e) => setFile(slot.key, e.target.files?.[0])}
                />
              </div>
            );
          })}
          <div style={{ marginTop: 18 }}>
            <button className="btn big" onClick={runExtraction} disabled={busy}>
              Read the documents →
            </button>
          </div>
        </div>
      )}

      {step === 1 && (
        <div className="card">
          <h2>Reading your documents…</h2>
          <p className="kv">
            <span className="spin" />
            Claude is extracting the meet details, events and entries. This can take a
            minute or two for large documents.
          </p>
        </div>
      )}

      {step === 2 && extraction && (
        <div className="card">
          <h2>Pick the session</h2>
          {mock ? (
            <div className="banner warn">
              Running in mock mode (no Claude API key configured) — showing the bundled
              City of Wells 2026 data instead of your uploaded documents.
            </div>
          ) : null}
          <p className="kv">
            <b>{extraction.meet.name}</b> · {extraction.meet.venue} · {extraction.meet.dates} ·{" "}
            {extraction.meet.course === "long" ? "Long course (50m)" : "Short course (25m)"}
          </p>
          {extraction.extractionNotes.length > 0 ? (
            <div className="banner warn">
              Notes from extraction:
              <ul className="notes">
                {extraction.extractionNotes.map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {mappingLooksOff ? (
            <div className="banner warn">
              The session labels in these documents don&rsquo;t all match the usual t1–t4
              pattern. Check the session numbers below before continuing.
            </div>
          ) : null}
          <div className="row" style={{ marginBottom: 6 }}>
            {sessionTags.map((tag) => (
              <div key={tag}>
                <label className="f">{tag} → session number</label>
                <input
                  type="text"
                  className="inline"
                  defaultValue={mapping[tag]}
                  onChange={(e) =>
                    setMapping((m) => ({ ...m, [tag]: parseInt(e.target.value, 10) || 0 }))
                  }
                />
              </div>
            ))}
          </div>
          <div className="sessPick">
            {sessionTags.map((tag) => {
              const info = extraction.sessions.find((s) => s.timelineTag === tag);
              const evs = extraction.events.filter((e) => e.timelineTag === tag);
              const n = evs.reduce((acc, e) => acc + e.swimmers.length, 0);
              return (
                <button key={tag} onClick={() => enterReview(tag)}>
                  <div className="sn">Session {mapping[tag]}</div>
                  <div className="sd">
                    {info ? `${info.day} ${info.ampm}`.trim() : tag} · {evs.length} events ·{" "}
                    {n} entries
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {step === 3 && extraction && (
        <>
          <div className="card">
            <h2>
              Review — Session {sessionNumber} ({sessionLabel})
            </h2>
            <div className="banner ok">
              Entry count check: {entryCount} entries across {events.length} events will go
              on the sheet.
            </div>
            {discrepancies.length > 0 ? (
              <div className="banner warn">
                Attendance discrepancies (for your information — the sheet is unchanged):
                <ul className="notes">
                  {discrepancies.map((d, i) => (
                    <li key={i}>{d}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            <div className="row">
              <div>
                <label className="f">Meet name</label>
                <input type="text" value={meet.name} onChange={(e) => setMeet({ ...meet, name: e.target.value })} />
              </div>
              <div>
                <label className="f">Venue</label>
                <input type="text" value={meet.venue} onChange={(e) => setMeet({ ...meet, venue: e.target.value })} />
              </div>
            </div>
            <div className="row">
              <div>
                <label className="f">Course</label>
                <select value={meet.course} onChange={(e) => setMeet({ ...meet, course: e.target.value })}>
                  <option value="long">Long course — 50m pool</option>
                  <option value="short">Short course — 25m pool</option>
                </select>
              </div>
              <div>
                <label className="f">Club</label>
                <input type="text" value={meet.club} onChange={(e) => setMeet({ ...meet, club: e.target.value })} />
              </div>
            </div>
          </div>

          {events.map((ev, evIdx) => {
            const n = splitCount(ev.distanceM, poolLengthM);
            return (
              <div className="eventCard" key={ev.number}>
                <div className="ehdr">
                  Event {ev.number} · {ev.gender} · {ev.distanceM}m {ev.stroke}
                  <span className="meta">
                    {ev.swimmers.length} swimmer{ev.swimmers.length !== 1 ? "s" : ""}
                    {n > 0 ? ` · ${n} × ${poolLengthM}m splits` : " · no splits"}
                  </span>
                </div>
                <table className="swimmers">
                  <thead>
                    <tr>
                      <th style={{ width: "28%" }}>First name</th>
                      <th style={{ width: "28%" }}>Surname</th>
                      <th style={{ width: "12%" }}>Age</th>
                      <th style={{ width: "22%" }}>Entry time</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortSwimmers(ev.swimmers).map((sw) => {
                      const swIdx = ev.swimmers.indexOf(sw);
                      return (
                        <tr key={swIdx}>
                          <td>
                            <input value={sw.first} onChange={(e) => updateSwimmer(evIdx, swIdx, "first", e.target.value)} />
                          </td>
                          <td>
                            <input value={sw.surname} onChange={(e) => updateSwimmer(evIdx, swIdx, "surname", e.target.value)} />
                          </td>
                          <td>
                            <input value={sw.age ?? ""} onChange={(e) => updateSwimmer(evIdx, swIdx, "age", e.target.value)} />
                          </td>
                          <td>
                            <input value={sw.entryTime} onChange={(e) => updateSwimmer(evIdx, swIdx, "entryTime", e.target.value)} />
                          </td>
                          <td>
                            <button className="rm" title="Remove swimmer" onClick={() => removeSwimmer(evIdx, swIdx)}>
                              ✕
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <button className="addSwimmer" onClick={() => addSwimmer(evIdx)}>
                  + Add swimmer
                </button>
              </div>
            );
          })}

          <div className="actions" style={{ marginTop: 18 }}>
            <button className="btn subtle" onClick={() => setStep(2)}>
              ← Back to sessions
            </button>
            <button className="btn big" onClick={generate} disabled={busy || entryCount === 0}>
              Generate the pack →
            </button>
          </div>
        </>
      )}

      {step === 4 && (
        <div className="card">
          <h2>Generating…</h2>
          <p className="kv">
            <span className="spin" />
            Building the sheet and saving the pack.
          </p>
        </div>
      )}
    </main>
  );
}
