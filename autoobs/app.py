"""
Observation Sheets — pure-Python single-page web app with Google OAuth.

Upload a Confirmed Entries file (required) and a Meet pack (recommended); the
backend parses them with pdfplumber and generates a print-ready PDF of coach
observation sheets. No AI, no external API calls — runs on a plain Ubuntu box.

Auth:
  - All pages require a Google-authenticated session.
  - Only emails in data/approved_users.json (plus the hardcoded ADMIN_EMAIL)
    can log in. Everyone else sees a "no access" page.
  - ADMIN_EMAIL can add/remove approved users via the admin panel.

Run (dev):   venv/bin/python app.py
Run (prod):  venv/bin/gunicorn -w 1 --threads 8 -b 0.0.0.0:8000 app:app
             (one worker + threads so background generation shares state)

Required env vars:
  GOOGLE_CLIENT_ID      — from Google Cloud Console
  GOOGLE_CLIENT_SECRET  — from Google Cloud Console
  SECRET_KEY            — any long random string (sessions won't survive restarts without it)
"""
from __future__ import annotations
import functools
import io
import json
import os
import secrets
import threading
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from authlib.integrations.flask_client import OAuth
from flask import (Flask, Response, abort, jsonify, redirect,
                   request, send_file, session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix

import parse
import pdfgen

# ── load .env for local dev (production uses system env vars via systemd) ─────
_env_file = Path(__file__).resolve().parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _, _v = _line.partition('=')
            os.environ.setdefault(_k.strip(), _v.strip())

# ── constants ─────────────────────────────────────────────────────────────────

ADMIN_EMAIL = "planetguru@gmail.com"

# ── paths ─────────────────────────────────────────────────────────────────────

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
UPLOADS = DATA / "uploads"
PDFS = DATA / "pdfs"
INDEX = DATA / "index.json"
USERS_FILE = DATA / "approved_users.json"
for d in (DATA, UPLOADS, PDFS):
    d.mkdir(parents=True, exist_ok=True)

# ── app + oauth ───────────────────────────────────────────────────────────────

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_prefix=1)  # Caddy strips /obsheets prefix
app.config["MAX_CONTENT_LENGTH"] = 60 * 1024 * 1024
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=90)

_secret = os.environ.get("SECRET_KEY", "")
if not _secret:
    _secret = secrets.token_hex(32)
    print(
        "WARNING: SECRET_KEY not set — sessions will reset on every restart.\n"
        "         Set SECRET_KEY in the environment for production."
    )
app.secret_key = _secret

oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# ── job index (JSON file; survives restarts) ──────────────────────────────────

_lock = threading.Lock()


def _load() -> list[dict]:
    if INDEX.exists():
        try:
            return json.loads(INDEX.read_text())
        except json.JSONDecodeError:
            return []
    return []


def _save(jobs: list[dict]) -> None:
    tmp = INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(jobs, indent=2))
    tmp.replace(INDEX)


def _update(job_id: str, **fields) -> None:
    with _lock:
        jobs = _load()
        for j in jobs:
            if j["id"] == job_id:
                j.update(fields)
                break
        _save(jobs)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Recover from a crash: any job left "generating" at startup is marked failed.
with _lock:
    _jobs = _load()
    changed = False
    for j in _jobs:
        if j.get("status") == "generating":
            j["status"] = "error"
            j["error"] = "Generation was interrupted (server restarted). Please try again."
            changed = True
    if changed:
        _save(_jobs)

# ── approved users ────────────────────────────────────────────────────────────

_ulock = threading.Lock()


def _load_users() -> list[str]:
    with _ulock:
        if USERS_FILE.exists():
            try:
                return json.loads(USERS_FILE.read_text())
            except json.JSONDecodeError:
                return []
        return []


def _save_users(users: list[str]) -> None:
    with _ulock:
        cleaned = sorted({u.lower().strip() for u in users if u.strip()})
        tmp = USERS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cleaned, indent=2))
        tmp.replace(USERS_FILE)


def is_approved(email: str) -> bool:
    e = email.lower().strip()
    return e == ADMIN_EMAIL or e in _load_users()


# ── auth helpers ──────────────────────────────────────────────────────────────

def current_email() -> str | None:
    return session.get("email")


def require_auth(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not current_email():
            if request.path.startswith("/api/"):
                return jsonify({"error": "Not authenticated"}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return wrapper


def require_admin(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        email = current_email()
        if not email:
            return jsonify({"error": "Not authenticated"}), 401
        if email.lower() != ADMIN_EMAIL:
            return jsonify({"error": "Forbidden"}), 403
        return f(*args, **kwargs)
    return wrapper


def _html_esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


# ── generation worker ─────────────────────────────────────────────────────────

def _generate(job_id: str, entries_path: str, pack_path: str | None) -> None:
    try:
        meet = parse.parse_meet(entries_path, pack_path)
        if meet.entry_count == 0:
            raise ValueError(
                "No swimmer entries could be read from that file. Is it the "
                "Confirmed Entries report?")
        pdf = pdfgen.meet_to_pdf(meet)
        out = PDFS / f"{job_id}.pdf"
        out.write_bytes(pdf)
        slug = "".join(c if c.isalnum() else "_" for c in meet.name).strip("_") or "ObservationSheets"
        _update(
            job_id,
            status="ready",
            meet_name=meet.name,
            download_name=f"{slug}.pdf",
            course=meet.course,
            pool_length=meet.pool_length,
            entry_count=meet.entry_count,
            swimmer_count=meet.swimmer_count,
            sessions=[
                {"number": s.number, "events": len(s.events),
                 "entries": sum(len(e.swimmers) for e in s.events)}
                for s in meet.sessions
            ],
            warnings=meet.warnings,
            finished_at=_now(),
        )
    except Exception as exc:
        traceback.print_exc()
        _update(job_id, status="error", error=str(exc) or exc.__class__.__name__,
                finished_at=_now())
    finally:
        for p in (entries_path, pack_path):
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass


# ── auth routes ───────────────────────────────────────────────────────────────

@app.get("/login")
def login_page():
    if current_email():
        return redirect(url_for("index"))
    error_map = {
        "auth_failed": "Sign-in failed. Please try again.",
        "no_email": "Couldn't read your email address from Google.",
    }
    error = error_map.get(request.args.get("error", ""), "")
    error_div = f'<div class="err">{_html_esc(error)}</div>' if error else ""
    html = (LOGIN_HTML
            .replace("__ERROR_DIV__", error_div)
            .replace("__AUTH_GOOGLE_URL__", url_for("auth_google")))
    return Response(html, mimetype="text/html")


@app.get("/auth/google")
def auth_google():
    redirect_uri = (os.environ.get("GOOGLE_REDIRECT_URI")
                    or url_for("auth_callback", _external=True))
    return google.authorize_redirect(redirect_uri)


@app.get("/auth/google/callback")
def auth_callback():
    try:
        token = google.authorize_access_token()
    except Exception:
        traceback.print_exc()
        return redirect(url_for("login_page", error="auth_failed"))

    userinfo = token.get("userinfo") or {}
    email = userinfo.get("email", "").lower().strip()

    if not email:
        return redirect(url_for("login_page", error="no_email"))

    if not is_approved(email):
        html = (NOPERMISSION_HTML
                .replace("__EMAIL__", _html_esc(email))
                .replace("__LOGOUT_URL__", url_for("logout")))
        return Response(html, mimetype="text/html", status=403)

    session.permanent = True
    session["email"] = email
    return redirect(url_for("index"))


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


# ── api: current user ─────────────────────────────────────────────────────────

@app.get("/api/me")
@require_auth
def api_me():
    email = current_email()
    return jsonify({"email": email, "is_admin": email.lower() == ADMIN_EMAIL})


# ── api: admin user management ────────────────────────────────────────────────

@app.get("/api/admin/users")
@require_admin
def admin_list_users():
    return jsonify({"users": _load_users(), "admin": ADMIN_EMAIL})


@app.post("/api/admin/users")
@require_admin
def admin_add_user():
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").lower().strip()
    if not email or "@" not in email:
        return jsonify({"ok": False, "error": "Invalid email address."}), 400
    if email == ADMIN_EMAIL:
        return jsonify({"ok": False, "error": "That address is already the permanent admin."}), 400
    users = _load_users()
    if email not in users:
        users.append(email)
        _save_users(users)
    return jsonify({"ok": True, "users": _load_users()})


@app.post("/api/admin/delete_user")
@require_admin
def admin_delete_user():
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").lower().strip()
    if email == ADMIN_EMAIL:
        return jsonify({"ok": False, "error": "Cannot remove the permanent admin."}), 400
    users = [u for u in _load_users() if u.lower() != email]
    _save_users(users)
    return jsonify({"ok": True, "users": _load_users()})


# ── app routes (all require auth) ─────────────────────────────────────────────

@app.get("/")
@require_auth
def index() -> Response:
    html = (INDEX_HTML
            .replace("__LOGIN_URL__", url_for("login_page"))
            .replace("__LOGOUT_URL__", url_for("logout")))
    return Response(html, mimetype="text/html")


@app.get("/api/jobs")
@require_auth
def api_jobs():
    with _lock:
        jobs = _load()
    public = [
        {k: v for k, v in j.items() if k not in ("entries_path", "pack_path")}
        for j in sorted(jobs, key=lambda j: j["created_at"], reverse=True)
    ]
    return jsonify(public)


@app.post("/api/generate")
@require_auth
def api_generate():
    entries = request.files.get("entries")
    if not entries or not entries.filename:
        return jsonify({"ok": False, "error": "Please add the Confirmed Entries file."}), 400
    pack = request.files.get("meetpack")

    job_id = uuid.uuid4().hex
    entries_path = str(UPLOADS / f"{job_id}_entries.pdf")
    entries.save(entries_path)
    pack_path = None
    if pack and pack.filename:
        pack_path = str(UPLOADS / f"{job_id}_pack.pdf")
        pack.save(pack_path)

    job = {
        "id": job_id,
        "status": "generating",
        "meet_name": "Reading documents…",
        "created_at": _now(),
        "has_pack": pack_path is not None,
    }
    with _lock:
        jobs = _load()
        jobs.append(job)
        _save(jobs)

    threading.Thread(target=_generate, args=(job_id, entries_path, pack_path),
                     daemon=True).start()
    return jsonify({"ok": True, "id": job_id})


@app.get("/download/<job_id>")
@require_auth
def download(job_id: str):
    if not job_id.isalnum():
        abort(404)
    path = PDFS / f"{job_id}.pdf"
    if not path.exists():
        abort(404)
    with _lock:
        job = next((j for j in _load() if j["id"] == job_id), None)
    name = (job or {}).get("download_name", "ObservationSheets.pdf")
    return send_file(path, mimetype="application/pdf", as_attachment=False,
                     download_name=name)


@app.post("/api/delete/<job_id>")
@require_auth
def delete(job_id: str):
    if not job_id.isalnum():
        abort(404)
    with _lock:
        jobs = _load()
        jobs = [j for j in jobs if j["id"] != job_id]
        _save(jobs)
    p = PDFS / f"{job_id}.pdf"
    if p.exists():
        p.unlink()
    return jsonify({"ok": True})


@app.get("/blank/<sheet_type>")
@require_auth
def blank_sheet(sheet_type: str):
    if sheet_type not in ('regular', 'long', 'sprint'):
        abort(404)
    pdf = pdfgen.blank_pdf(sheet_type)
    names = {'long': 'LongDistanceSheets.pdf', 'sprint': 'SprintSheets.pdf'}
    name = names.get(sheet_type, 'RegularSheets.pdf')
    return send_file(io.BytesIO(pdf), mimetype='application/pdf',
                     as_attachment=False, download_name=name)


# ── login page ────────────────────────────────────────────────────────────────

LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign In — Observation Sheets</title>
<style>
  :root{--ink:#10243f;--accent:#0a558c;--line:#9fb2c6;--soft:#eef3f8;--gray:#5b6e84;}
  *{box-sizing:border-box;}
  body{font-family:"Helvetica Neue",Helvetica,Segoe UI,Roboto,sans-serif;color:var(--ink);
    background:linear-gradient(180deg,#f4f8fc,#e8eff7);margin:0;min-height:100vh;
    display:flex;align-items:center;justify-content:center;padding:20px;}
  .card{background:#fff;border:1.5px solid var(--line);border-radius:14px;
    padding:44px 40px;max-width:380px;width:100%;
    box-shadow:0 4px 20px rgba(16,36,63,.08);text-align:center;}
  h1{margin:0 0 6px;font-size:26px;letter-spacing:.3px;}
  h1 span{color:var(--accent);}
  .sub{color:var(--gray);font-size:14px;margin:0 0 32px;}
  .google-btn{display:inline-flex;align-items:center;gap:11px;background:#fff;
    border:1.5px solid #d0d5dd;border-radius:10px;padding:13px 24px;text-decoration:none;
    color:var(--ink);font-size:15px;font-weight:600;transition:box-shadow .15s;}
  .google-btn:hover{box-shadow:0 2px 10px rgba(0,0,0,.12);}
  .err{margin-top:20px;padding:11px 14px;background:#fdecea;border-radius:8px;
    font-size:13px;color:#8e2418;font-weight:600;}
</style>
</head>
<body>
<div class="card">
  <h1>Observation<span>Sheets</span></h1>
  <p class="sub">Bridgwater ASC — coach recording sheets</p>
  <a href="__AUTH_GOOGLE_URL__" class="google-btn">
    <svg width="20" height="20" viewBox="0 0 24 24">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
      <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/>
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
    </svg>
    Sign in with Google
  </a>
  __ERROR_DIV__
</div>
</body>
</html>"""


# ── no-permission page ────────────────────────────────────────────────────────

NOPERMISSION_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Access Denied — Observation Sheets</title>
<style>
  :root{--ink:#10243f;--accent:#0a558c;--line:#9fb2c6;--soft:#eef3f8;--gray:#5b6e84;}
  *{box-sizing:border-box;}
  body{font-family:"Helvetica Neue",Helvetica,Segoe UI,Roboto,sans-serif;color:var(--ink);
    background:linear-gradient(180deg,#f4f8fc,#e8eff7);margin:0;min-height:100vh;
    display:flex;align-items:center;justify-content:center;padding:20px;}
  .card{background:#fff;border:1.5px solid var(--line);border-radius:14px;
    padding:44px 40px;max-width:400px;width:100%;
    box-shadow:0 4px 20px rgba(16,36,63,.08);text-align:center;}
  h1{margin:0 0 16px;font-size:22px;}
  p{color:var(--gray);font-size:14px;margin:0 0 10px;line-height:1.5;}
  .email{font-weight:700;color:var(--ink);}
  .signout{margin-top:28px;padding:11px 22px;background:var(--soft);
    border:1.5px solid var(--line);border-radius:9px;font-size:14px;
    font-weight:600;cursor:pointer;color:var(--ink);font-family:inherit;}
  .signout:hover{background:#dde6ef;}
</style>
</head>
<body>
<div class="card">
  <h1>Access not granted</h1>
  <p>You signed in as <span class="email">__EMAIL__</span>.</p>
  <p>That address isn't on the approved list. Ask the administrator to add it.</p>
  <form method="post" action="__LOGOUT_URL__">
    <button type="submit" class="signout">Sign out and try another account</button>
  </form>
</div>
</body>
</html>"""


# ── main app page ─────────────────────────────────────────────────────────────

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Observation Sheets &mdash; Bridgwater ASC</title>
<style>
  :root{--ink:#10243f;--accent:#0a558c;--line:#9fb2c6;--soft:#eef3f8;--gray:#5b6e84;}
  *{box-sizing:border-box;}
  body{font-family:"Helvetica Neue",Helvetica,Segoe UI,Roboto,sans-serif;color:var(--ink);
    background:linear-gradient(180deg,#f4f8fc,#e8eff7);margin:0;min-height:100vh;}
  .wrap{max-width:760px;margin:0 auto;padding:28px 20px 60px;}
  header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;}
  header h1{margin:0;font-size:28px;letter-spacing:.5px;}
  header h1 span{color:var(--accent);}
  header p{margin:5px 0 0;color:var(--gray);font-size:14px;}
  #user-bar{text-align:right;font-size:13px;color:var(--gray);flex-shrink:0;padding-top:4px;}
  #user-bar .email{font-weight:600;color:var(--ink);}
  #user-bar .so-btn{margin-top:5px;display:block;background:none;border:1.5px solid var(--line);
    border-radius:6px;color:var(--gray);cursor:pointer;font-size:12px;padding:4px 10px;
    font-family:inherit;width:100%;}
  #user-bar .so-btn:hover{border-color:var(--accent);color:var(--accent);}
  .card{background:#fff;border:1.5px solid var(--line);border-radius:12px;
    padding:20px 22px;margin-top:18px;box-shadow:0 2px 8px rgba(16,36,63,.06);}
  #banner{display:none;margin-top:16px;padding:13px 16px;border-radius:9px;font-size:14px;
    font-weight:600;white-space:pre-wrap;}
  #banner.err{display:block;background:#fdecea;border:2px solid #c0392b;color:#8e2418;}
  .slots{display:flex;gap:14px;flex-wrap:wrap;}
  .slot{flex:1;min-width:220px;border:2.5px dashed var(--accent);border-radius:11px;
    background:var(--soft);padding:22px 16px;text-align:center;cursor:pointer;transition:background .15s;}
  .slot.hover{background:#dcebf7;}
  .slot.filled{border-style:solid;border-color:#2e7d46;background:#eef9f0;cursor:default;}
  .slot .t{font-weight:800;font-size:15px;}
  .slot .h{font-size:12.5px;color:var(--gray);margin-top:6px;}
  .slot .file{font-size:13px;font-weight:700;color:#205c33;margin-top:8px;word-break:break-word;}
  .slot .rm{display:inline-block;margin-top:8px;font-size:12.5px;color:#c0392b;
    font-weight:700;cursor:pointer;text-decoration:underline;}
  .go{display:block;width:100%;margin-top:16px;border:none;border-radius:10px;cursor:pointer;
    background:var(--accent);color:#fff;font-size:17px;font-weight:800;padding:15px;font-family:inherit;}
  .go:hover{background:#0c69ad;}
  .go:disabled{opacity:.45;cursor:not-allowed;}
  h2{font-size:16px;color:var(--accent);margin:0 0 6px;}
  .job{display:flex;align-items:center;gap:12px;border:1.5px solid var(--line);border-radius:10px;
    padding:13px 15px;margin-top:10px;background:#fff;text-decoration:none;color:inherit;}
  .job.ready{cursor:pointer;}
  .job.ready:hover{border-color:var(--accent);background:#f7fbff;}
  .job .nm{flex:1;min-width:0;}
  .job .nm .title{font-weight:700;font-size:15px;}
  .job .nm .sub{font-size:12.5px;color:var(--gray);margin-top:2px;}
  .badge{font-size:11.5px;font-weight:800;text-transform:uppercase;letter-spacing:.5px;
    padding:5px 11px;border-radius:999px;white-space:nowrap;}
  .badge.generating{background:#fdf6e3;color:#7a5d00;border:1.5px solid #b58900;}
  .badge.ready{background:#eef9f0;color:#205c33;border:1.5px solid #2e7d46;}
  .badge.error{background:#fdecea;color:#8e2418;border:1.5px solid #c0392b;}
  .spin{display:inline-block;width:13px;height:13px;border:2.5px solid #e3d9b0;
    border-top-color:#b58900;border-radius:50%;animation:spin .8s linear infinite;
    vertical-align:-2px;margin-right:6px;}
  @keyframes spin{to{transform:rotate(360deg);}}
  .warn{font-size:12px;color:#7a5d00;margin-top:4px;}
  .del{background:none;border:none;color:var(--gray);cursor:pointer;font-size:16px;padding:4px 8px;}
  .del:hover{color:#c0392b;}
  .empty{color:var(--gray);font-size:14px;}
  .blank-btn{display:inline-flex;flex-direction:column;gap:4px;padding:13px 18px;min-width:190px;
    border:2px solid var(--accent);border-radius:10px;text-decoration:none;
    color:var(--accent);background:var(--soft);}
  .blank-btn:hover{background:#dcebf7;}
  .bb-title{font-weight:800;font-size:15px;}
  .bb-sub{font-size:11.5px;color:var(--gray);}
  /* admin panel */
  #admin-panel{display:none;}
  .admin-note{font-size:13px;color:var(--gray);margin:0 0 14px;line-height:1.5;}
  .admin-perm{font-size:13px;color:var(--ink);padding:9px 12px;background:var(--soft);
    border-radius:7px;margin-bottom:14px;}
  .user-row{display:flex;align-items:center;gap:10px;padding:9px 0;
    border-bottom:1px solid var(--line);font-size:14px;}
  .user-row:last-child{border-bottom:none;}
  .user-email{flex:1;}
  .rm-user{background:none;border:1.5px solid #c0392b;border-radius:6px;
    color:#c0392b;cursor:pointer;font-size:12.5px;font-weight:700;padding:4px 10px;
    font-family:inherit;}
  .rm-user:hover{background:#fdecea;}
  .add-row{display:flex;gap:8px;margin-top:14px;}
  .add-row input{flex:1;padding:9px 12px;border:1.5px solid var(--line);
    border-radius:8px;font-size:14px;font-family:inherit;color:var(--ink);}
  .add-row input:focus{outline:none;border-color:var(--accent);}
  .add-btn{padding:9px 18px;background:var(--accent);color:#fff;border:none;
    border-radius:8px;font-size:14px;cursor:pointer;font-weight:700;font-family:inherit;}
  .add-btn:hover{background:#0c69ad;}
  .admin-err{color:#8e2418;font-size:13px;margin-top:8px;display:none;font-weight:600;}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>Observation<span>Sheets</span></h1>
      <p>Bridgwater ASC &mdash; coach recording sheets from the gala paperwork</p>
    </div>
    <div id="user-bar"></div>
  </header>

  <div id="banner"></div>

  <div class="card">
    <div class="slots">
      <div class="slot" id="slot-entries" data-key="entries">
        <div class="t">Confirmed Entries</div>
        <div class="h">Drop the file here, or click to upload</div>
      </div>
      <div class="slot" id="slot-meetpack" data-key="meetpack">
        <div class="t">Meet pack</div>
        <div class="h">Drop the file here, or click to upload</div>
      </div>
    </div>
    <input type="file" id="fi-entries" accept=".pdf,application/pdf" style="display:none">
    <input type="file" id="fi-meetpack" accept=".pdf,application/pdf" style="display:none">
    <button class="go" id="go" disabled>Generate Observation Sheets</button>
  </div>

  <div class="card">
    <h2>Blank sheets</h2>
    <p style="font-size:13.5px;color:var(--gray);margin:0 0 14px">No paperwork needed &mdash; download pre-formatted blank recording sheets.</p>
    <div style="display:flex;gap:12px;flex-wrap:wrap">
      <a href="blank/sprint" target="_blank" class="blank-btn">
        <span class="bb-title">Sprint</span>
        <span class="bb-sub">4 &times; 25m splits &middot; SC 50m &amp; 100m &middot; 5/page &middot; 2 pages</span>
      </a>
      <a href="blank/regular" target="_blank" class="blank-btn">
        <span class="bb-title">Regular</span>
        <span class="bb-sub">8 &times; 50m splits &middot; 5 swimmers/page &middot; 2 pages</span>
      </a>
      <a href="blank/long" target="_blank" class="blank-btn">
        <span class="bb-title">Long Distance</span>
        <span class="bb-sub">30 &times; 50m splits &middot; 3 swimmers/page &middot; 2 pages</span>
      </a>
    </div>
  </div>

  <div class="card">
    <h2>Observation sheets</h2>
    <div id="list"><p class="empty">Generated sheets will appear here.</p></div>
  </div>

  <div class="card" id="admin-panel">
    <h2>Admin: Approved Users</h2>
    <p class="admin-note">Users listed here can log in. Remove them to revoke access immediately.</p>
    <div class="admin-perm" id="admin-perm-row"></div>
    <div id="admin-list"></div>
    <div class="add-row">
      <input type="email" id="admin-add-input" placeholder="user@gmail.com">
      <button class="add-btn" onclick="adminAdd()">Add user</button>
    </div>
    <div class="admin-err" id="admin-err"></div>
  </div>
</div>

<script>
"use strict";
const files = {entries:null, meetpack:null};
const $ = id => document.getElementById(id);

function showErr(msg){const b=$('banner');b.className='err';b.textContent=msg;window.scrollTo(0,0);}
function clearErr(){const b=$('banner');b.className='';b.style.display='none';}
window.onerror = m => { showErr('Something went wrong: '+m); return false; };

function renderSlot(key){
  const slot = $('slot-'+key);
  const f = files[key];
  const title = key==='entries' ? 'Confirmed Entries' : 'Meet pack';
  if(f){
    slot.classList.add('filled');
    slot.innerHTML = '<div class="t">'+title+'</div>'+
      '<div class="file">✓ '+f.name+'</div>'+
      '<span class="rm" data-key="'+key+'">remove</span>';
  } else {
    slot.classList.remove('filled');
    slot.innerHTML = '<div class="t">'+title+'</div>'+
      '<div class="h">Drop the file here, or click to upload</div>';
  }
  $('go').disabled = !files.entries;
}

function setFile(key, f){
  if(f && !/\.pdf$/i.test(f.name)){ showErr('"'+f.name+'" is not a PDF. Please upload a PDF file.'); return; }
  clearErr(); files[key]=f||null; renderSlot(key);
}

['entries','meetpack'].forEach(key=>{
  const slot=$('slot-'+key), input=$('fi-'+key);
  slot.addEventListener('click', e=>{
    if(e.target.classList.contains('rm')){ e.stopPropagation(); setFile(key,null); return; }
    if(!files[key]) input.click();
  });
  input.addEventListener('change', ()=> setFile(key, input.files[0]));
  ['dragover','dragenter'].forEach(ev=>slot.addEventListener(ev, e=>{e.preventDefault();slot.classList.add('hover');}));
  ['dragleave','dragend','drop'].forEach(ev=>slot.addEventListener(ev, e=>{e.preventDefault();slot.classList.remove('hover');}));
  slot.addEventListener('drop', e=>{ const f=e.dataTransfer.files&&e.dataTransfer.files[0]; if(f) setFile(key,f); });
});

$('go').addEventListener('click', async ()=>{
  if(!files.entries) return;
  clearErr();
  const fd = new FormData();
  fd.append('entries', files.entries);
  if(files.meetpack) fd.append('meetpack', files.meetpack);
  $('go').disabled = true;
  try{
    const r = await fetch('api/generate', {method:'POST', body:fd});
    const j = await r.json();
    if(!j.ok){ showErr(j.error||'Generation failed.'); $('go').disabled=false; return; }
    files.entries=null; files.meetpack=null; renderSlot('entries'); renderSlot('meetpack');
    poll();
  }catch(err){ showErr('Could not start generation: '+err); $('go').disabled=false; }
});

function jobRow(j){
  if(j.status==='ready'){
    const sess = (j.sessions||[]).length;
    const sub = j.entry_count+' entries · '+sess+' session'+(sess!==1?'s':'')+
      ' · '+(j.course==='long'?'long course (50m)':'short course (25m)');
    let warn = (j.warnings&&j.warnings.length)? '<div class="warn">⚠ '+j.warnings.join(' ')+'</div>':'';
    return '<a class="job ready" href="download/'+j.id+'" target="_blank">'+
      '<div class="nm"><div class="title">'+esc(j.meet_name)+'</div><div class="sub">'+sub+'</div>'+warn+'</div>'+
      '<span class="badge ready">Ready ↓</span>'+
      '<button class="del" title="Remove" onclick="del(event,\''+j.id+'\')">&#x2715;</button></a>';
  }
  if(j.status==='error'){
    return '<div class="job"><div class="nm"><div class="title">Couldn\'t generate</div>'+
      '<div class="sub">'+esc(j.error||'Unknown error')+'</div></div>'+
      '<span class="badge error">Error</span>'+
      '<button class="del" title="Remove" onclick="del(event,\''+j.id+'\')">&#x2715;</button></div>';
  }
  return '<div class="job"><div class="nm"><div class="title"><span class="spin"></span>Generating…</div>'+
    '<div class="sub">Reading the documents and building the sheets</div></div>'+
    '<span class="badge generating">Working</span></div>';
}

function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

async function del(e, id){ e.preventDefault(); e.stopPropagation();
  await fetch('api/delete/'+id, {method:'POST'}); poll(); }

let timer=null;
async function poll(){
  try{
    const jobs = await (await fetch('api/jobs')).json();
    const list=$('list');
    if(!jobs.length){ list.innerHTML='<p class="empty">Generated sheets will appear here.</p>'; }
    else { list.innerHTML = jobs.map(jobRow).join(''); }
    const working = jobs.some(j=>j.status==='generating');
    clearTimeout(timer);
    if(working) timer=setTimeout(poll, 1200);
  }catch(err){ clearTimeout(timer); timer=setTimeout(poll, 2500); }
}

// ── auth / user bar ───────────────────────────────────────────────────────────

async function initUser(){
  try{
    const r = await fetch('api/me');
    if(r.status === 401){ window.location='__LOGIN_URL__'; return; }
    const me = await r.json();
    const bar = $('user-bar');
    bar.innerHTML = '<div class="email">'+esc(me.email)+'</div>'+
      '<form method="post" action="__LOGOUT_URL__" style="margin:0">'+
      '<button type="submit" class="so-btn">Sign out</button></form>';
    if(me.is_admin){
      $('admin-panel').style.display='block';
      loadAdminUsers();
    }
  }catch(e){ /* ignore — poll will surface auth errors */ }
}

// ── admin panel ───────────────────────────────────────────────────────────────

async function loadAdminUsers(){
  try{
    const r = await fetch('api/admin/users');
    const data = await r.json();
    $('admin-perm-row').textContent = '🔒 Permanent admin: '+data.admin;
    const users = data.users || [];
    const list = $('admin-list');
    if(!users.length){
      list.innerHTML='<p class="empty" style="margin:0 0 4px">No additional users approved yet.</p>';
    } else {
      list.innerHTML = users.map(u=>
        '<div class="user-row">'+
        '<span class="user-email">'+esc(u)+'</span>'+
        '<button class="rm-user" onclick="adminRemove(\''+esc(u)+'\')">Remove</button>'+
        '</div>'
      ).join('');
    }
  }catch(e){}
}

async function adminAdd(){
  const input = $('admin-add-input');
  const email = input.value.trim();
  const errDiv = $('admin-err');
  errDiv.style.display='none';
  if(!email){ errDiv.textContent='Enter an email address.'; errDiv.style.display='block'; return; }
  try{
    const r = await fetch('api/admin/users',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({email})
    });
    const data = await r.json();
    if(!data.ok){ errDiv.textContent=data.error; errDiv.style.display='block'; return; }
    input.value='';
    loadAdminUsers();
  }catch(e){ errDiv.textContent='Request failed. Try again.'; errDiv.style.display='block'; }
}

async function adminRemove(email){
  try{
    await fetch('api/admin/delete_user',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({email})
    });
    loadAdminUsers();
  }catch(e){}
}

initUser();
poll();
</script>
</body>
</html>"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"\n  Observation Sheets running at http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, threaded=True)
