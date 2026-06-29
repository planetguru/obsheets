# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo does

ObSheets generates print-ready PDF coach observation sheets for swimming galas. Upload a Confirmed Entries PDF (and optionally a Meet pack PDF); the app parses them and produces one page set per session, swimmers ordered slowest-first.

**No AI, no external APIs.** Pure Python only — this is a hard constraint.

---

## Primary tool: `autoobs/`

This is the live, deployed app. The older `app.py`/`generate.py`/`pdfgen.py` at the repo root are a simpler local-only predecessor; `webapp/` is a superseded Next.js prototype.

### Required environment variables

All three must be set before the app will work with real Google sign-in:

| Variable | Where to get it |
|---|---|
| `GOOGLE_CLIENT_ID` | Google Cloud Console → OAuth 2.0 credentials |
| `GOOGLE_CLIENT_SECRET` | Same credential |
| `SECRET_KEY` | Any long random string — `python3 -c "import secrets; print(secrets.token_hex(32))"` |

On Linode, add these as `Environment=...` lines in `/etc/systemd/system/obsheets.service`.
For local dev, `export` them in the terminal before running, or set `GOOGLE_REDIRECT_URI` explicitly.

The hardcoded admin is `planetguru@gmail.com` (`ADMIN_EMAIL` constant in `app.py`). All other users must be added via the admin panel after logging in.

### Run locally

```sh
cd autoobs
python3 -m venv venv
venv/bin/pip install -r requirements.txt
export GOOGLE_CLIENT_ID=...
export GOOGLE_CLIENT_SECRET=...
export SECRET_KEY=...
venv/bin/python app.py          # http://127.0.0.1:8000
```

Or double-click `ObservationSheets.command` from the repo root (requires env vars to be set system-wide, or edit the `.command` file to export them).

### Run the reliability gate

```sh
cd autoobs
venv/bin/python verify.py /path/to/sample-galas
```

Parses all sample galas and asserts parsed entry count == an independent raw count from the source text. Must exit 0 before any parse change is considered correct.

### Deploy (Linode / Ubuntu)

```sh
venv/bin/gunicorn -w 1 --threads 8 -b 0.0.0.0:8000 app:app
```

Must be **1 worker + threads** — background PDF generation uses a module-level thread and job index; multiple workers would have separate state.

---

## Architecture of `autoobs/`

Three files, no shared state between them except through `app.py`:

| File | Role |
|------|------|
| `parse.py` | Extracts entries + meet structure from PDFs (pdfplumber). The event number is the join key between entries and meet pack. |
| `pdfgen.py` | Draws sheets to PDF. Pure stdlib — no external PDF library. All coordinates are in points on A4 portrait. |
| `app.py` | Flask single-page app. Background generation via `threading.Thread`; job state in `data/index.json` (survives restarts). |
| `verify.py` | Reliability gate — not part of the web app. |

### Parsing logic (`parse.py`)

`parse_meet(entries_path, pack_path)` returns a `Meet` with a list of `Event` objects, each containing `Entry` objects (swimmer name, age, entry time, gender).

Handles **four entry formats** detected automatically:
1. **GoMotion committed-athletes** — `(d1/t2)` day/time-slot tags, `#N` event markers
2. **GoMotion "Meet Entry Report"** — two layout variants
3. **Hy-Tek "All Events"** — column-structured with rank/time columns
4. **Hy-Tek "Team Entries"** — similar but team-grouped

Session assignment priority: `(d/t)` tags → meet-pack "Session N / Event N" map → single session with a warning.

Splits: one box per pool length (50m = LC, 25m = SC), determined from the meet pack. Single-length events have no splits row.

Order: `NT` entries first (no time), then slowest → fastest, ties broken alphabetically by surname then first name.

### PDF writer (`pdfgen.py`)

`Doc` is a minimal raw PDF builder. Page coordinates are **top-of-page origin** (unlike PDF spec which is bottom-left). `render_session(meet, session_events)` is the entry point that returns bytes.

### Auth flow (`app.py`)

All routes require a session. Unauthenticated requests redirect to `/login`; API calls return 401.

1. `/login` → login page with "Sign in with Google" button
2. `/auth/google` → redirect to Google OAuth
3. `/auth/google/callback` → verify email; if approved → set `session["email"]`, redirect to `/`; if not → 403 no-permission page
4. `/logout` (POST) → clear session, redirect to `/login`

Approved users live in `data/approved_users.json`. `ADMIN_EMAIL` is always approved regardless of that file. The admin panel (only visible to `ADMIN_EMAIL`) calls `GET/POST /api/admin/users` and `POST /api/admin/delete_user` to manage the list.

`werkzeug.middleware.proxy_fix.ProxyFix` is applied so `url_for(..., _external=True)` generates `https://` URLs when running behind nginx.

### Job lifecycle (`app.py`)

`POST /api/generate` → creates a job with `status: "generating"`, spawns a thread → thread calls `parse` + `pdfgen`, writes PDF to `data/pdfs/`, updates `data/index.json` → frontend polls `GET /api/jobs` every 2 s.

---

## What not to commit

- `autoobs/data/` — generated PDFs and job index (gitignored)
- Any PDF containing real swimmer names or gala data
- `autoobs/venv/` (gitignored)

The `.gitignore` covers these, but double-check before committing fixture or sample files.
