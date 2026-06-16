# ObSheets — Session Resume Guide

## How to continue this work
Open Claude Code in this directory (`~/Development/obsheets`). The memory files at
`~/.claude/projects/-Users-christopherlacy-hulbert-Development-obsheets/memory/`
will be loaded automatically and give full context.

---

## Current state (updated 2026-06-16)

### 🆕 `autoobs/` — pure-Python app, NO AI (this is now the primary tool)
Chris pivoted: he wants pure-Python parsing (no LLM/API/token cost) so it hosts
on a basic Linode Ubuntu box, and a dead-simple single-page UI. Built in
`autoobs/` and **fully working/verified against 5 real galas**.

- **Launcher:** double-click `ObservationSheets.command` → http://127.0.0.1:8000
- **Stack:** Flask + pdfplumber (pure Python, pip-installable, no system binaries).
  `pdfgen.py` (stdlib PDF writer) reused from the old tool.
- **Single page:** two upload slots — **Confirmed Entries** (required) and
  **Meet pack** (optional) — each with drop/click + a "remove" affordance; one
  "Generate Observation Sheets" button; a queue list below showing
  generating → ready (click row to download the PDF) / error, with ✕ to remove.
  Background generation via a thread; the page polls `/api/jobs`.
- **Parsing (`parse.py`):** the **event number is the join key**. Entries give
  swimmers/ages/times/event-descriptions; meet pack gives session grouping +
  pool length (LC=50m / SC=25m). Session priority: `(d/t)` tags in entries →
  meet-pack "Session N / Event N" map → single session (with a warning).
  Handles 3+ entry formats (Hy-Tek "All Events", two GoMotion "Meet Entry
  Report" styles, committed-athletes `(d1/t2)`). Slowest-first order, NT top.
- **Verified:** `verify.py` parses all 5 sample galas (in
  `~/Downloads/auto-obsheets/`) and asserts parsed entry count == independent raw
  token count — **all exact**: LDCC 126, Bobby Tutt 199, Bristol 185, Wells 187,
  NUEL 144. (Wells 187 includes the Event-13 entry the LLM had silently dropped.)
  Distance events render fine (1500m LC→25m = 60 split boxes, one page).
- **Deploy:** `requirements.txt` + `obsheets.service` (gunicorn `-w 1 --threads 8`
  so background threads share state). See `autoobs/README.md`.
- The Next.js/Claude `webapp/` is **superseded** by this for Chris's stated
  hosting/cost constraints, but left in place.

## Earlier state (2026-06-12, evening)

### 🆕 Observation Packs web app (`webapp/`) — built from the formal brief
Built to `~/Downloads/observation-pack-app-build-brief.md`: a Next.js
(TypeScript) multi-user app with Google sign-in + email allowlist, a shared
"Previous packs" list (SQLite), a 5-step wizard (upload 4 labelled documents →
Claude extraction → session pick with configurable t→session mapping → editable
review with entry-count check + attendance discrepancies → generate), and a pack
view with Print / Download HTML.

- **Launcher:** double-click `ObservationPacks.command` → http://localhost:3000
- **Dev mode is ON** (`webapp/.env.local`): no sign-in needed, extraction uses
  the bundled Wells 2026 fixture. `webapp/SETUP.md` explains how to add the
  Google OAuth credentials and Anthropic API key to go live.
- **Architecture per brief:** LLM (claude-opus-4-8, forced JSON schema) only
  extracts; `src/lib/generator.ts` is the deterministic generator implementing
  the §5 rules + §8 template verbatim; 16 unit tests (`npm test`).
- **Verified:** session 3 pack output is identical in event/swimmer order to
  the hand-verified Python-generated sheet; splits per spec; count check 46/46.
- Real LLM extraction is **live and tested** (2026-06-13). Chris's API key is in
  `webapp/.env.local` (`ANTHROPIC_API_KEY=`), `EXTRACT_MOCK` is off. Friendly
  error messages map auth/credit/rate-limit failures to plain English.
- **Accuracy caveat (important):** on the Wells PDF, the LLM extracted 186/187
  entries — it dropped one swimmer's Event-13 entry (200 Back, Session 2). The
  deterministic Python parser got all 187. The §5.6 count-check CANNOT catch this
  because it compares the generator output to the LLM's own data, not to the
  source document — so LLM omissions pass silently. This is the same
  silent-data-loss risk Chris was burned by before. Likely future task: feed the
  authoritative Hy-Tek "Entries – All Events" report (only the committed-athletes
  export was provided in the test), and/or add an independent count cross-check.

### ✅ The simpler local tool still works (app.py)
Double-click **`ObSheets.command`** → a small Python web server starts and the
browser opens `http://127.0.0.1:8765`. Workflow on the page:

1. **Drop the entries PDF** (GoMotion "Committed Athletes" export) onto the page
2. **Check the details** — meet name, club, venue, per-day dates, session times
3. **Download** — per-session PDF, one combined all-sessions PDF, or HTML

The PDF download is generated directly in Python (`pdfgen.py`, pure stdlib —
no installs) and matches the navy/blue sheet design. No print dialog needed.

### Key files
| File | Purpose |
|------|---------|
| `webapp/` | **Observation Packs** — Next.js multi-user app (see above) |
| `ObservationPacks.command` | Double-click launcher → webapp on localhost:3000 |
| `app.py` | Older single-user local web app (drag-drop → PDF download) |
| `pdfgen.py` | Pure-stdlib PDF writer + sheet layout (used by app.py) |
| `generate.py` | Parser + HTML generator (also still works as a CLI) |
| `ObSheets.command` | Double-click launcher → starts `app.py` |

`index.html` (the old abandoned file:// web app) was removed 2026-06-12 — the
new app serves its page over localhost HTTP, which avoids all the file:// browser
restrictions that killed the old approach.

### Why this architecture
- Parsing stays in Python (`generate.py`) — battle-tested, no JS reimplementation
- Served over `http://127.0.0.1` so drag-drop/fetch work reliably (file:// did not)
- Every step shows status or a prominent error banner (lesson: silent JS failures
  are catastrophic for this user)
- The entry-count check runs on upload: if PDF entries ≠ sheet entries, the page
  shows a warning banner

### ✅ Verified 2026-06-12 (City of Wells Open Meet 2026, `~/Downloads/Wells Entries V2.pdf`)
- 34 swimmers, 187 entries, all accounted for; 4 sessions; 46 PDF pages total
- Rendered pages visually checked: cover header, event headers, swimmer boxes,
  splits grids, comments boxes, "Event N (continued)" pagination, page footers

### Parser bugs fixed 2026-06-12 (in generate.py, shared by CLI and web app)
1. **Brody O'Brien missing entirely** — Mac-Roman apostrophe decoded as `Õ`
   broke the name regex; all 5 events silently dropped. Also affected the old
   "reference" sheet — `~/Downloads/Session3_Coach_Sheet.html` is NOT a valid
   comparison target.
2. **Event #14 misattributed** (one swimmer's entry credited to another) — a
   swimmer's first event row can render above their name line; detected via the
   sign-up-date marker and gender mismatch, held in a pending buffer for the
   next swimmer.
3. **Tie ordering** — equal entry times now sort alphabetically (was reversed).

---

## Likely next tasks
- **Hy-Tek entries support** for actual swimmer ages (currently age-group minimum)
- **TM attendance filtering** — only include swimmers on the session list
- **Relay events** — currently only individual events are parsed
