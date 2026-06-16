# Observation Packs — Setup Guide

A web app for Bridgwater ASC coaches: upload a gala's paperwork, review the
extracted data, and generate a printable poolside recording sheet. Packs are
shared with the whole allowlisted team.

## Try it right now (no setup)

Double-click **`ObservationPacks.command`** in the project folder. The app runs
in **development mode**:

- No sign-in needed (you're "Dev Coach")
- Document reading uses the bundled City of Wells 2026 data instead of the
  Claude API, so you can walk the whole journey without an API key

## Going live — three things to set up

The development shortcuts are controlled by `.env.local` in this folder.
For real use you need:

### 1. A Claude API key (so it reads YOUR documents)

1. Go to <https://platform.claude.com/> and create an account
2. Create an API key and put it in `.env.local`:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   EXTRACT_MOCK=
   ```
   (leave `EXTRACT_MOCK` empty to turn the mock data off)

Each pack creation makes one Claude call to read the uploaded documents.
The coach always reviews and can correct the result before anything is generated.

### 2. Google sign-in (so each coach uses their own account)

1. Go to <https://console.cloud.google.com/> → create a project
2. **APIs & Services → OAuth consent screen** — configure as External, add the
   app name and your email
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   - Application type: Web application
   - Authorised redirect URI: `http://localhost:3000/api/auth/callback/google`
     (plus your real domain's equivalent when hosted, e.g.
     `https://packs.example.org/api/auth/callback/google`)
4. Put the client ID and secret in `.env.local`:
   ```
   AUTH_GOOGLE_ID=...apps.googleusercontent.com
   AUTH_GOOGLE_SECRET=...
   AUTH_SECRET=   ← generate with: openssl rand -base64 32
   AUTH_DEV_BYPASS=
   ```
   (leave `AUTH_DEV_BYPASS` empty to require real sign-in)

### 3. The coach allowlist

Only these emails can sign in — everyone else gets a polite "not authorised":

```
ALLOWED_EMAILS=you@gmail.com,headcoach@gmail.com,assistant@bridgwaterasc.org
```

## Hosting for the team

Running locally only works on your own Mac. For the team to share packs, host
it on any Node.js platform (Vercel, Railway, a club server, …):

- `npm run build` then `npm start`
- Set the same environment variables there (don't copy the dev bypass!)
- The SQLite database lives in `data/obsheets.db` — the host needs persistent
  disk, or swap `src/lib/db.ts` for Postgres later

## Development notes

- `npm test` — unit tests for the deterministic sheet generator (the §5 rules
  from the build brief: splits, slowest-first/NT-top ordering, tie-breaks,
  page breaks, discrepancy flagging)
- `npm run dev` — dev server with hot reload
- Extraction is LLM-based (`src/lib/extract.ts`, Claude `claude-opus-4-8` with a
  forced JSON schema); generation is pure deterministic code
  (`src/lib/generator.ts`) so the layout and rules are identical every time
- A pack stores its reviewed source JSON, so sheets can be regenerated if the
  template ever changes
