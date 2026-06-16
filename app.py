#!/usr/bin/env python3
"""
ObSheets web app.
Run:  python3 app.py   (or double-click ObSheets.command)
Opens http://127.0.0.1:8765 — drop a GoMotion "Committed Athletes" PDF on the
page, check the meet details, then download recording sheets as PDF or HTML.
Parsing and HTML generation are reused from generate.py; PDFs from pdfgen.py.
"""
import json, os, re, sys, tempfile, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

import generate
import pdfgen

PORT_RANGE = range(8765, 8775)
STATE = {}   # parsed meet + generated documents (single local user)

# ── FRONT-END PAGE ────────────────────────────────────────────────────────────

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ObSheets — Coach Recording Sheets</title>
<style>
  :root{--ink:#10243f;--accent:#0a558c;--line:#9fb2c6;--soft:#eef3f8;--gray:#5b6e84;}
  *{box-sizing:border-box;}
  body{font-family:"Helvetica Neue",Helvetica,Segoe UI,Roboto,sans-serif;color:var(--ink);
    background:linear-gradient(180deg,#f4f8fc,#e8eff7);margin:0;min-height:100vh;}
  .wrap{max-width:680px;margin:0 auto;padding:28px 20px 60px;}
  header h1{margin:0;font-size:30px;letter-spacing:.5px;}
  header p{margin:6px 0 0;color:var(--gray);font-size:15px;}
  .card{background:#fff;border:1.5px solid var(--line);border-radius:12px;
    padding:20px 22px;margin-top:18px;box-shadow:0 2px 8px rgba(16,36,63,.06);}
  .card h2{margin:0 0 12px;font-size:17px;color:var(--accent);}
  #banner{display:none;margin-top:18px;padding:14px 18px;border-radius:10px;
    font-size:15px;font-weight:600;white-space:pre-wrap;}
  #banner.err{display:block;background:#fdecea;border:2px solid #c0392b;color:#8e2418;}
  #banner.warn{display:block;background:#fdf6e3;border:2px solid #b58900;color:#7a5d00;}
  #drop{border:2.5px dashed var(--accent);border-radius:12px;background:var(--soft);
    padding:46px 20px;text-align:center;cursor:pointer;font-size:19px;font-weight:700;
    color:var(--accent);transition:background .15s;}
  #drop.hover{background:#dcebf7;}
  #drop small{display:block;margin-top:8px;font-size:13px;font-weight:500;color:var(--gray);}
  #parseStatus{margin-top:12px;font-size:14px;color:var(--gray);}
  .ok{background:#eef9f0;border:1.5px solid #2e7d46;color:#205c33;border-radius:8px;
    padding:10px 14px;font-size:14px;margin-bottom:14px;}
  label.f{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.6px;
    color:var(--gray);font-weight:700;margin:12px 0 4px;}
  input[type=text],input[type=date],select{width:100%;padding:9px 10px;font-size:15px;
    border:1.5px solid var(--line);border-radius:7px;color:var(--ink);background:#fff;}
  .row{display:flex;gap:14px;flex-wrap:wrap;}.row>div{flex:1;min-width:160px;}
  .sessrow{display:flex;align-items:center;gap:10px;margin-top:8px;}
  .sessrow .nm{flex:1;font-size:14px;font-weight:600;}
  .sessrow select{width:150px;}
  button,.btn{display:inline-block;border:none;border-radius:9px;cursor:pointer;
    background:var(--accent);color:#fff;font-size:16px;font-weight:700;
    padding:13px 22px;margin-top:18px;text-decoration:none;text-align:center;}
  button:hover,.btn:hover{background:#0c69ad;}
  .btn.big{display:block;font-size:18px;padding:16px;}
  .dl{display:flex;align-items:center;gap:10px;border:1.5px solid var(--line);
    border-radius:10px;padding:12px 14px;margin-top:10px;background:#fff;}
  .dl .nm{flex:1;font-size:15px;font-weight:700;}
  .dl .nm small{display:block;font-weight:500;color:var(--gray);font-size:12px;margin-top:2px;}
  .dl a{font-size:14px;padding:9px 14px;margin:0;}
  .dl a.alt{background:#fff;color:var(--accent);border:1.5px solid var(--accent);}
  .muted{color:var(--gray);font-size:13px;margin-top:10px;}
  .hidden{display:none;}
</style></head><body><div class="wrap">
<header><h1>ObSheets</h1>
<p>Coach recording sheets from your club system entries PDF · Bridgwater ASC</p></header>
<div id="banner"></div>

<section class="card" id="step1">
  <h2>1 · Your entries PDF</h2>
  <div id="drop">Drop your entries PDF here<small>or click to choose the file
  — it&rsquo;s the &ldquo;Committed Athletes&rdquo; export from your club system</small></div>
  <input type="file" id="fi" accept=".pdf,application/pdf" style="display:none">
  <div id="parseStatus"></div>
</section>

<section class="card hidden" id="step2">
  <h2>2 · Check the details</h2>
  <div class="ok" id="summary"></div>
  <div class="row">
    <div><label class="f">Meet name</label><input type="text" id="meetName"></div>
    <div><label class="f">Club</label><input type="text" id="club" value="Bridgwater ASC"></div>
  </div>
  <label class="f">Venue</label>
  <input type="text" id="venue" placeholder="e.g. Millfield School Pool">
  <div id="days"></div>
  <button id="gen">Create my sheets</button>
</section>

<section class="card hidden" id="step3">
  <h2>3 · Your sheets</h2>
  <a class="btn big" id="allpdf" href="#">&#11015;&#65038; Download ALL sessions — one PDF</a>
  <div id="list"></div>
  <p class="muted">PDFs are ready to print as-is. The HTML version opens in a new
  tab if you&rsquo;d rather use File &rarr; Print.</p>
</section>
</div>
<script>
'use strict';
const $ = id => document.getElementById(id);
function showErr(msg){ const b=$('banner'); b.className='err'; b.style.display='block';
  b.textContent='Something went wrong: '+msg; window.scrollTo(0,0); }
function showWarn(msg){ const b=$('banner'); b.className='warn'; b.style.display='block';
  b.textContent=msg; window.scrollTo(0,0); }
function clearBanner(){ $('banner').className=''; $('banner').style.display='none'; }
window.onerror = (m)=>{ showErr(m); return false; };
window.onunhandledrejection = e=>showErr(e.reason && e.reason.message || e.reason);

let meetInfo = null;

$('drop').addEventListener('click', ()=>$('fi').click());
$('fi').addEventListener('change', ()=>{ if($('fi').files[0]) upload($('fi').files[0]); });
['dragover','dragenter'].forEach(ev=>$('drop').addEventListener(ev, e=>{
  e.preventDefault(); $('drop').classList.add('hover'); }));
['dragleave','dragend'].forEach(ev=>$('drop').addEventListener(ev, e=>{
  e.preventDefault(); $('drop').classList.remove('hover'); }));
$('drop').addEventListener('drop', e=>{
  e.preventDefault(); $('drop').classList.remove('hover');
  const f = e.dataTransfer.files && e.dataTransfer.files[0];
  if(!f){ showErr('No file detected in the drop — try clicking the box to choose it instead.'); return; }
  upload(f);
});

async function upload(file){
  clearBanner();
  if(!/\.pdf$/i.test(file.name)){
    showErr('"'+file.name+'" is not a PDF. Please drop the entries PDF from your club system.');
    return;
  }
  $('parseStatus').textContent = 'Reading "'+file.name+'"…';
  const resp = await fetch('/parse', {method:'POST', body:file,
    headers:{'X-Filename': encodeURIComponent(file.name)}});
  const data = await resp.json();
  if(!data.ok){ $('parseStatus').textContent=''; showErr(data.error); return; }
  meetInfo = data;
  $('parseStatus').textContent = '';
  if(data.warning) showWarn(data.warning);
  $('summary').textContent = 'Found '+data.swimmers+' swimmers, '+data.entries+
    ' entries across '+data.sessions.length+' session'+(data.sessions.length!==1?'s':'')+
    ' — '+(data.course==='long'?'long':'short')+' course. All entries accounted for ✓';
  $('meetName').value = data.meetName || '';
  renderDays(data);
  $('step2').classList.remove('hidden');
  $('step2').scrollIntoView({behavior:'smooth'});
}

function renderDays(data){
  const days = {};
  data.sessions.forEach(s=>{ (days[s.day] = days[s.day]||[]).push(s); });
  let html = '';
  Object.keys(days).sort().forEach(d=>{
    html += '<label class="f">Day '+d+' date</label>'+
      '<input type="date" id="date_'+d+'">';
    days[d].forEach((s,i)=>{
      const def = i===0 ? 'Morning' : (i===1 ? 'Afternoon' : 'Evening');
      html += '<div class="sessrow"><div class="nm">Session '+s.num+
        ' &middot; Events '+s.range+' &middot; '+s.entries+' entries</div>'+
        '<select id="time_'+s.num+'">'+
        ['Morning','Afternoon','Evening'].map(t=>'<option'+(t===def?' selected':'')+'>'+t+'</option>').join('')+
        '</select></div>';
    });
  });
  $('days').innerHTML = html;
}

$('gen').addEventListener('click', async ()=>{
  clearBanner();
  const dates = {}, times = {};
  meetInfo.sessions.forEach(s=>{
    const d = $('date_'+s.day); if(d && d.value) dates[s.day]=d.value;
    times[s.num] = $('time_'+s.num).value;
  });
  $('gen').textContent = 'Creating sheets…';
  const resp = await fetch('/generate', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({meetName:$('meetName').value, club:$('club').value,
      venue:$('venue').value, dates, times})});
  const data = await resp.json();
  $('gen').textContent = 'Create my sheets';
  if(!data.ok){ showErr(data.error); return; }
  $('allpdf').href = data.allPdf;
  $('list').innerHTML = data.sessions.map(s=>
    '<div class="dl"><div class="nm">Session '+s.num+' &middot; '+s.label+
    '<small>'+s.events+' events &middot; '+s.entries+' entries</small></div>'+
    '<a class="btn" href="'+s.pdf+'">Download PDF</a>'+
    '<a class="btn alt" href="'+s.html+'" target="_blank">Open HTML</a></div>').join('');
  $('step3').classList.remove('hidden');
  $('step3').scrollIntoView({behavior:'smooth'});
});
</script></body></html>"""

# ── HELPERS ───────────────────────────────────────────────────────────────────

def slugify(name):
    return re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_') or 'Meet'

def format_date(iso):
    """'2026-05-30' → 'Saturday 30 May 2026'."""
    try:
        import datetime
        d = datetime.date.fromisoformat(iso)
        return f"{generate.DAYS[d.weekday()]} {d.day} {generate.MONTHS[d.month - 1]} {d.year}"
    except (ValueError, TypeError):
        return iso or ''

def parse_pdf(body):
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tf:
        tf.write(body)
        tmp = tf.name
    try:
        lines = generate.extract_text(tmp)
        meet_name, course, swimmers = generate.parse(lines)
    finally:
        os.unlink(tmp)
    if not swimmers:
        raise ValueError(
            "No swimmer entries found in that PDF. Make sure it's the "
            "“Committed Athletes” export from your club system "
            "(Events → Sign-up → Print → Committed Athletes), "
            "not the printed meet programme.")
    raw_count = sum(len(generate.EVT_RE.findall(l)) for l in lines)
    attributed = sum(len(s['events']) for s in swimmers)
    sessions = generate.organise(swimmers)
    STATE.clear()
    STATE.update({'meet_name': meet_name, 'course': course,
                  'swimmers': swimmers, 'sessions': sessions})
    sess_list = []
    for sn, sd in sorted(sessions.items()):
        ev_nums = sorted(sd['events'])
        sess_list.append({
            'num': sn, 'day': sd['day'],
            'events': len(sd['events']),
            'entries': sum(len(e['swimmers']) for e in sd['events'].values()),
            'range': f"{min(ev_nums)}–{max(ev_nums)}"})
    out = {'ok': True, 'meetName': meet_name, 'course': course,
           'swimmers': len(swimmers), 'entries': attributed, 'sessions': sess_list}
    if attributed != raw_count:
        out['warning'] = (f"Heads up: the PDF contains {raw_count} entries but only "
                          f"{attributed} could be matched to swimmers. Please check the "
                          f"finished sheets against the entries list before the meet.")
    return out

def build_docs(cfg):
    if 'sessions' not in STATE:
        raise ValueError("Please drop the entries PDF first.")
    meet_name = (cfg.get('meetName') or '').strip() or STATE['meet_name'] or 'Meet'
    club = (cfg.get('club') or '').strip() or 'Bridgwater ASC'
    venue = (cfg.get('venue') or '').strip()
    course = STATE['course']
    dates = cfg.get('dates') or {}
    times = cfg.get('times') or {}
    slug = slugify(meet_name)

    labels, docs, sess_out = {}, {}, []
    sorted_sessions = sorted(STATE['sessions'].items())
    for sn, sd in sorted_sessions:
        date_str = format_date(dates.get(str(sd['day']), ''))
        t = times.get(str(sn), '')
        labels[sn] = (f"{date_str} ({t})" if date_str and t
                      else date_str or (f"({t})" if t else f"Session {sn}"))
        html = generate.gen_session(sn, sd, meet_name, club, venue, course, labels[sn])
        pdf = pdfgen.session_pdf(sn, sd, meet_name, club, venue, course, labels[sn])
        docs[sn] = {'html': html.encode('utf-8'), 'pdf': pdf}
        sess_out.append({'num': sn, 'label': labels[sn],
                         'events': len(sd['events']),
                         'entries': sum(len(e['swimmers']) for e in sd['events'].values()),
                         'pdf': f"/download/{sn}.pdf", 'html': f"/download/{sn}.html"})
    docs['all'] = pdfgen.meet_pdf(sorted_sessions, meet_name, club, venue, course, labels)
    STATE['docs'] = docs
    STATE['slug'] = slug
    return {'ok': True, 'sessions': sess_out, 'allPdf': '/download/all.pdf'}

# ── HTTP SERVER ───────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

    def _send(self, code, body, ctype, extra=None):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode('utf-8'), 'application/json')

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            self._send(200, PAGE.encode('utf-8'), 'text/html; charset=utf-8')
            return
        m = re.match(r'^/download/(all|\d+)\.(pdf|html)$', self.path)
        if m and STATE.get('docs'):
            which, kind = m.group(1), m.group(2)
            slug = STATE.get('slug', 'Meet')
            if which == 'all' and kind == 'pdf':
                body, fname = STATE['docs']['all'], f"{slug}_AllSessions.pdf"
            else:
                doc = STATE['docs'].get(int(which)) if which != 'all' else None
                if not doc:
                    self._send(404, b'Not found', 'text/plain'); return
                body = doc[kind]
                fname = f"{slug}_Session{which}.{kind}"
            if kind == 'pdf':
                self._send(200, body, 'application/pdf',
                           {'Content-Disposition': f'attachment; filename="{fname}"'})
            else:
                self._send(200, body, 'text/html; charset=utf-8',
                           {'Content-Disposition': f'inline; filename="{fname}"'})
            return
        self._send(404, b'Not found', 'text/plain')

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            if self.path == '/parse':
                self._json(parse_pdf(body))
            elif self.path == '/generate':
                self._json(build_docs(json.loads(body or b'{}')))
            else:
                self._json({'ok': False, 'error': 'Unknown action'}, 404)
        except ValueError as e:
            self._json({'ok': False, 'error': str(e)})
        except Exception as e:
            self._json({'ok': False, 'error': f'{type(e).__name__}: {e}'})

def main():
    server = None
    for port in PORT_RANGE:
        try:
            server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
            break
        except OSError:
            continue
    if server is None:
        print("Could not start: ports 8765-8774 are all in use.")
        sys.exit(1)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"\n  ObSheets is running at {url}")
    print("  Your browser should open automatically.")
    print("  Keep this window open while you work; close it when you're done.\n")
    if '--no-browser' not in sys.argv:
        threading.Timer(0.5, lambda: os.system(f'open "{url}"')).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  ObSheets stopped. You can close this window.")

if __name__ == '__main__':
    main()
