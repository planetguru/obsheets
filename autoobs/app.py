"""
Observation Sheets — pure-Python single-page web app.

Upload a Confirmed Entries file (required) and a Meet pack (recommended); the
backend parses them with pdfplumber and generates a print-ready PDF of coach
observation sheets. No AI, no external API calls — runs on a plain Ubuntu box.

Run (dev):   venv/bin/python app.py
Run (prod):  venv/bin/gunicorn -w 1 --threads 8 -b 0.0.0.0:8000 app:app
             (one worker + threads so background generation shares state)
"""
from __future__ import annotations
import json
import os
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_file, abort, Response

import parse
import pdfgen

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
UPLOADS = DATA / "uploads"
PDFS = DATA / "pdfs"
INDEX = DATA / "index.json"
for d in (DATA, UPLOADS, PDFS):
    d.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 60 * 1024 * 1024  # 60 MB per request

_lock = threading.Lock()


# ── job index (JSON file; survives restarts) ──────────────────────────────────

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
    except Exception as exc:  # surface the reason, never fail silently
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


# ── routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def index() -> Response:
    return Response(INDEX_HTML, mimetype="text/html")


@app.get("/api/jobs")
def api_jobs():
    with _lock:
        jobs = _load()
    # newest first; strip internal fields
    public = [
        {k: v for k, v in j.items() if k not in ("entries_path", "pack_path")}
        for j in sorted(jobs, key=lambda j: j["created_at"], reverse=True)
    ]
    return jsonify(public)


@app.post("/api/generate")
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


# ── single-page front-end ─────────────────────────────────────────────────────

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Observation Sheets — Bridgwater ASC</title>
<style>
  :root{--ink:#10243f;--accent:#0a558c;--line:#9fb2c6;--soft:#eef3f8;--gray:#5b6e84;}
  *{box-sizing:border-box;}
  body{font-family:"Helvetica Neue",Helvetica,Segoe UI,Roboto,sans-serif;color:var(--ink);
    background:linear-gradient(180deg,#f4f8fc,#e8eff7);margin:0;min-height:100vh;}
  .wrap{max-width:760px;margin:0 auto;padding:28px 20px 60px;}
  header h1{margin:0;font-size:28px;letter-spacing:.5px;}
  header h1 span{color:var(--accent);}
  header p{margin:5px 0 0;color:var(--gray);font-size:14px;}
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
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Observation<span>Sheets</span></h1>
    <p>Bridgwater ASC — coach recording sheets from the gala paperwork</p>
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
    <h2>Observation sheets</h2>
    <div id="list"><p class="empty">Generated sheets will appear here.</p></div>
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
    const r = await fetch('/api/generate', {method:'POST', body:fd});
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
    return '<a class="job ready" href="/download/'+j.id+'" target="_blank">'+
      '<div class="nm"><div class="title">'+esc(j.meet_name)+'</div><div class="sub">'+sub+'</div>'+warn+'</div>'+
      '<span class="badge ready">Ready ↓</span>'+
      '<button class="del" title="Remove" onclick="del(event,\''+j.id+'\')">✕</button></a>';
  }
  if(j.status==='error'){
    return '<div class="job"><div class="nm"><div class="title">Couldn\'t generate</div>'+
      '<div class="sub">'+esc(j.error||'Unknown error')+'</div></div>'+
      '<span class="badge error">Error</span>'+
      '<button class="del" title="Remove" onclick="del(event,\''+j.id+'\')">✕</button></div>';
  }
  return '<div class="job"><div class="nm"><div class="title"><span class="spin"></span>Generating…</div>'+
    '<div class="sub">Reading the documents and building the sheets</div></div>'+
    '<span class="badge generating">Working</span></div>';
}

function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

async function del(e, id){ e.preventDefault(); e.stopPropagation();
  await fetch('/api/delete/'+id, {method:'POST'}); poll(); }

let timer=null;
async function poll(){
  try{
    const jobs = await (await fetch('/api/jobs')).json();
    const list=$('list');
    if(!jobs.length){ list.innerHTML='<p class="empty">Generated sheets will appear here.</p>'; }
    else { list.innerHTML = jobs.map(jobRow).join(''); }
    const working = jobs.some(j=>j.status==='generating');
    clearTimeout(timer);
    if(working) timer=setTimeout(poll, 1200);
  }catch(err){ /* keep last view; retry shortly */ clearTimeout(timer); timer=setTimeout(poll, 2500); }
}
poll();
</script>
</body>
</html>"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"\n  Observation Sheets running at http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, threaded=True)
