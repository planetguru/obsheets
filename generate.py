#!/usr/bin/env python3
"""
ObSheets — Coach Recording Sheet Generator
Usage: python3 generate.py /path/to/entries.pdf
Outputs one HTML file per session to ~/Desktop/ObSheets/
"""
import sys, os, zlib, re
from collections import defaultdict
from pathlib import Path

# ── PDF EXTRACTION ────────────────────────────────────────────────────────────

def pdf_str_decode(s):
    # Õ/Ô are Mac-Roman curly apostrophes (0xD5/0xD4) seen through latin-1 —
    # without this, names like O'Brien fail the name regex and vanish entirely
    return (s.replace('\\n','\n').replace('\\r','\r').replace('\\t','\t')
             .replace('\\(','(').replace('\\)',')').replace('\\\\','\\')
             .replace('’',"'").replace('‘',"'").replace('Õ',"'").replace('Ô',"'"))

def extract_bt_text(bt):
    parts = []
    for m in re.finditer(r'\(([^)\\]*(?:\\.[^)\\]*)*)\)\s*Tj', bt):
        parts.append((m.start(), pdf_str_decode(m.group(1))))
    for m in re.finditer(r'\[([^\]]*)\]\s*TJ', bt):
        txt = ''.join(pdf_str_decode(sm.group(1))
                      for sm in re.finditer(r'\(([^)\\]*(?:\\.[^)\\]*)*)\)', m.group(1)))
        parts.append((m.start(), txt))
    parts.sort(); return ''.join(p[1] for p in parts)

def extract_text(pdf_path):
    with open(pdf_path, 'rb') as f:
        data = f.read()
    SS, ES = b'stream', b'endstream'
    items = []; page_num = 0; i = 0
    while i < len(data) - 6:
        if data[i:i+6] == SS and (i == 0 or data[i-1] in (10, 13)):
            ds = i + 6
            if data[ds] == 13: ds += 1
            if data[ds] == 10: ds += 1
            de = data.find(ES, ds)
            if de < 0: i += 1; continue
            re_ = de
            if data[re_-1] == 10: re_ -= 1
            if data[re_-1] == 13: re_ -= 1
            try: st = zlib.decompress(data[ds:re_]).decode('latin-1')
            except:
                try: st = data[ds:re_].decode('latin-1')
                except: i = de + 9; continue
            if 'Tj' in st or 'TJ' in st:
                blk = re.compile(r'q\s+[\d.]+\s+0\s+0\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)\s+cm\s+BT([\s\S]*?)ET')
                for bm in blk.finditer(st):
                    txt = extract_bt_text(bm.group(3)).strip()
                    if txt: items.append({'x': float(bm.group(1)), 'y': float(bm.group(2)),
                                          'pg': page_num, 'text': txt})
                page_num += 1
            i = de + 9
        else:
            i += 1
    # Group by y into lines
    lmap = defaultdict(lambda: {'pg': 0, 'y': 0, 'its': []})
    for it in items:
        rY = round(it['y'] / 4) * 4
        key = f"{it['pg']}_{rY}"
        lmap[key]['pg'] = it['pg']; lmap[key]['y'] = rY; lmap[key]['its'].append(it)
    lines = sorted(lmap.values(), key=lambda v: (v['pg'], -v['y']))
    lines = [' '.join(i['text'] for i in sorted(v['its'], key=lambda x: x['x'])).strip()
             for v in lines]
    lines = [l.replace('’', "'").replace('‘', "'").replace('Õ', "'").replace('Ô', "'")
             for l in lines if l]
    # Hyphenated name fragment merge
    for i in range(len(lines) - 1):
        ws = lines[i].split()
        if ws and re.match(r'^[A-Z][A-Za-z]+-$', ws[0]):
            lines[i] = lines[i][len(ws[0]):].strip()
            lines[i+1] = ws[0] + lines[i+1]
    return lines

# ── PARSER ────────────────────────────────────────────────────────────────────

EVT_RE = re.compile(
    r"#(\d+)\s*[A-Z]*\s*\(\s*d(\d+)\s*/\s*t(\d+)\s*\)\s*:\s*([BG])\s+"
    r"(\d+)-(\d+)\s+(\d+)\s+(\w+(?:\s+\w+)?)\s+\(\s*([^)]+?)\s+Approved\s*\)")

NOISE = {'Junior','Squad','Performance','Bridgwater','Amateur','Swimming','Club',
         'Token','Link','Legacy','Compete','Pre','Notes','Member','Billing','Group',
         'Location','Approved','Meet','Events','Individual','Registration','Print','NOW','Page'}

def parse_time(s):
    return re.sub(r'[LSMlsm]$', '', s).strip()

def parse(lines):
    raw = '\n'.join(lines)
    mn = re.search(r'Meet Info:\s*(.+)', raw)
    meet_name = mn.group(1).split('\n')[0].strip() if mn else ''
    course = 'long' if re.search(r'\d+L\s+Approved', raw) else 'short'

    swimmers = {}; cur = None
    pending = []  # event rows that belong to the NEXT swimmer (block-start row split off above the name line)

    def add_event(key, m):
        if not key or key not in swimmers: return
        ev_num = int(m.group(1))
        if any(e['eventNum'] == ev_num for e in swimmers[key]['events']): return
        swimmers[key]['events'].append({
            'eventNum': ev_num, 'session': int(m.group(3)), 'day': int(m.group(2)),
            'gender': 'Girls' if m.group(4) == 'G' else 'Boys',
            'ageMin': int(m.group(5)), 'distance': int(m.group(7)),
            'stroke': m.group(8).strip(), 'entryTime': parse_time(m.group(9))})

    def set_sw(sur, fst):
        nonlocal cur
        key = f"{sur}|{fst}"
        if key not in swimmers:
            swimmers[key] = {'surname': sur, 'firstname': fst, 'ageMin': None, 'events': []}
        cur = key
        for pm in pending: add_event(key, pm)
        pending.clear()
        return key

    def find_firstname(i):
        for j in range(i + 1, min(i + 10, len(lines))):
            nl = lines[j].strip()
            if not nl: continue
            if ',' in nl: break
            ws = nl.split()
            word = ws[0] if ws else ''
            if (word and not word.startswith('#') and re.match(r'^[A-Z][a-z]+$', word)
                    and 2 <= len(word) <= 14 and word not in NOISE):
                return word
        return ''

    for i, line in enumerate(lines):
        t = line.strip()
        if not t: continue
        m = re.match(r"^([A-Z][A-Za-z'\-]+(?:\s+[A-Za-z'\-]+)?),\s+([A-Za-z][A-Za-z'\-]+)\s", t + ' ')
        if m and not re.match(r'^\d', m.group(2)):
            k = set_sw(m.group(1).strip(), m.group(2).strip())
            em = EVT_RE.search(t)
            if em: add_event(k, em)
            continue
        m = re.match(r"^([A-Z][A-Za-z'\-]+(?:\s+[A-Za-z'\-]+)?),\s+(#\d)", t)
        if m:
            k = set_sw(m.group(1).strip(), find_firstname(i))
            em = EVT_RE.search(t)
            if em: add_event(k, em)
            continue
        m = re.match(r"^([A-Z][A-Za-z'\-]+(?:\s+[A-Za-z'\-]+)?),\s*$", t)
        if m: set_sw(m.group(1).strip(), find_firstname(i)); continue
        m = EVT_RE.search(t)
        if m:
            # A sign-up date after the entry marks a swimmer's FIRST row — it can render
            # above the name line, so hold it for the next swimmer. A gender flip vs the
            # current swimmer's events is the same situation seen another way.
            gender = 'Girls' if m.group(4) == 'G' else 'Boys'
            cur_evs = swimmers[cur]['events'] if cur in swimmers else []
            if (re.search(r'\d{2}/\d{2}/\d{2}', t[m.end():])
                    or (cur_evs and all(e['gender'] != gender for e in cur_evs))):
                pending.append(m)
            else:
                add_event(cur, m)

    if pending:
        print(f"  WARNING: {len(pending)} entry line(s) could not be matched to any swimmer")
    for sw in swimmers.values():
        if sw['events']: sw['ageMin'] = sw['events'][0]['ageMin']
    return meet_name, course, [s for s in swimmers.values() if s['events']]

# ── SESSION ORGANISATION ──────────────────────────────────────────────────────

def organise(swimmers):
    sessions = defaultdict(lambda: {'day': 0, 'events': {}})
    for sw in swimmers:
        for ev in sw['events']:
            sn = ev['session']
            sessions[sn]['day'] = ev['day']
            if ev['eventNum'] not in sessions[sn]['events']:
                sessions[sn]['events'][ev['eventNum']] = {
                    'eventNum': ev['eventNum'], 'gender': ev['gender'],
                    'distance': ev['distance'], 'stroke': ev['stroke'], 'swimmers': []}
            sessions[sn]['events'][ev['eventNum']]['swimmers'].append({
                'firstname': sw['firstname'], 'surname': sw['surname'],
                'age': sw['ageMin'], 'entryTime': ev['entryTime']})
    return sessions

# ── HTML GENERATION ───────────────────────────────────────────────────────────

STROKE = {'Back':'Backstroke','Breast':'Breaststroke','Free':'Freestyle',
          'Fly':'Butterfly','Medley':'IM','IM':'IM'}

def stroke_disp(s): return STROKE.get(s, s)

def esc(s): return (str(s or '').replace('&','&amp;').replace('<','&lt;')
                                .replace('>','&gt;').replace('"','&quot;'))

def to_sec(t):
    if not t or t == 'NT': return float('inf')
    p = t.split(':')
    return int(p[0]) * 60 + float(p[1]) if len(p) == 2 else float(p[0])

def sort_swimmers(lst):
    # Slowest first, NT at the very top; ties alphabetical by surname then firstname
    return sorted(lst, key=lambda s: (-to_sec(s['entryTime']), s['surname'], s['firstname']))

CSS = """<style>
  :root{--ink:#10243f;--accent:#0a558c;--line:#9fb2c6;--soft:#eef3f8;}
  *{box-sizing:border-box;}html,body{margin:0;padding:0;}
  body{font-family:"Helvetica Neue",Helvetica,Segoe UI,Roboto,sans-serif;
    color:var(--ink);background:#fff;line-height:1.25;
    -webkit-print-color-adjust:exact;print-color-adjust:exact;}
  .page{max-width:760px;margin:0 auto;padding:22px 26px;}
  header.cover{border:2px solid var(--ink);border-radius:10px;padding:16px 20px;
    margin-bottom:18px;background:linear-gradient(180deg,#fff,var(--soft));}
  header.cover h1{margin:0;font-size:20px;letter-spacing:.5px;}
  header.cover .sub{margin-top:4px;font-size:14px;color:var(--accent);font-weight:700;}
  header.cover .meta{margin-top:8px;font-size:12px;color:#43566b;}
  section.event{break-before:page;page-break-before:always;margin-top:4px;}
  section.event:first-of-type{break-before:auto;page-break-before:auto;}
  .ehead{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;
    background:#fff;color:var(--accent);border:2px solid var(--accent);
    padding:8px 14px;border-radius:7px;margin-bottom:12px;}
  .ehead .enum{font-weight:800;font-size:16px;letter-spacing:.5px;}
  .ehead .etitle{font-weight:700;font-size:15px;}
  .ehead .emeta{margin-left:auto;font-size:12px;color:#5b6e84;}
  .swimmer{border:1.4px solid var(--line);border-radius:8px;
    padding:9px 12px 11px;margin-bottom:11px;
    break-inside:avoid;page-break-inside:avoid;}
  .srow{display:flex;align-items:center;gap:12px;}
  .name{font-weight:700;font-size:15px;flex:1;min-width:0;}
  .name .evtag{font-size:10px;color:#7488a0;font-weight:700;margin-right:7px;}
  .name .age{color:#5b6e84;font-weight:500;font-size:13px;}
  .field{display:flex;align-items:center;gap:6px;}
  .field label{font-size:10px;text-transform:uppercase;letter-spacing:.6px;color:#5b6e84;}
  .entry{min-width:62px;text-align:center;font-size:13px;font-weight:600;
    background:var(--soft);border:1px solid var(--line);border-radius:4px;padding:3px 6px;}
  .blank{width:78px;height:24px;border:1px solid var(--ink);border-radius:4px;background:#fff;}
  .blank.heat{width:48px;}
  .srow2{display:flex;align-items:flex-end;gap:10px;margin-top:9px;}
  .splabel{font-size:10px;text-transform:uppercase;letter-spacing:.6px;
    color:#5b6e84;white-space:nowrap;padding-bottom:3px;}
  .splits{display:flex;gap:6px;flex-wrap:wrap;}
  .split{display:flex;flex-direction:column;align-items:center;gap:2px;}
  .split .dist{font-size:9px;color:#7488a0;}
  .split .line{width:54px;height:26px;border:1px solid var(--ink);border-radius:4px;background:#fff;}
  .comments{margin-top:9px;}
  .comments label{font-size:10px;text-transform:uppercase;letter-spacing:.6px;color:#5b6e84;}
  .cbox{margin-top:3px;height:54px;border:1px solid var(--ink);border-radius:5px;
    background:#fff;background-image:repeating-linear-gradient(
      transparent,transparent 25px,#dde6ef 25px,#dde6ef 26px);}
  @page{size:A4 portrait;margin:12mm;}
  @media print{.page{max-width:none;padding:0;}}
</style>"""

def gen_swimmer(sw, ev_num, distance, pool_len):
    splits_html = ''
    if distance > pool_len:
        n = distance // pool_len
        boxes = ''.join(
            f'<div class="split"><span class="dist">{(i+1)*pool_len}</span>'
            f'<span class="line"></span></div>' for i in range(n))
        splits_html = (f'<div class="srow2"><div class="splabel">{pool_len}m splits</div>'
                       f'<div class="splits">{boxes}</div></div>')
    age_html = f' <span class="age">({sw["age"]})</span>' if sw.get('age') is not None else ''
    return f"""    <div class="swimmer">
      <div class="srow">
        <div class="name"><span class="evtag">#{ev_num}</span>{esc(sw['firstname'])} {esc(sw['surname'])}{age_html}</div>
        <div class="field"><label>Heat</label><div class="blank heat"></div></div>
        <div class="field"><label>Entry</label><div class="entry">{esc(sw['entryTime'])}</div></div>
        <div class="field"><label>Time</label><div class="blank"></div></div>
      </div>
      {splits_html}
      <div class="comments"><label>Coach&#8217;s comments</label><div class="cbox"></div></div>
    </div>"""

def gen_session(sess_num, sess_data, meet_name, club, venue, course, date_label):
    pool_len = 50 if course == 'long' else 25
    course_lbl = f'Long Course ({pool_len}m)' if course == 'long' else f'Short Course ({pool_len}m)'
    events = sorted(sess_data['events'].values(), key=lambda e: e['eventNum'])
    ev_nums = [e['eventNum'] for e in events]
    ev_range = f'Events {min(ev_nums)}–{max(ev_nums)}' if ev_nums else ''
    has_splits = any(e['distance'] > pool_len for e in events)
    splits_note = f' · splits every {pool_len}m' if has_splits else ''

    parts = [f'<!doctype html><html lang="en"><head><meta charset="utf-8">',
             f'<meta name="viewport" content="width=device-width,initial-scale=1">',
             f'<title>Session {sess_num} – {esc(club)}</title>',
             CSS, '</head><body><div class="page">',
             f'  <header class="cover">',
             f'    <h1>{esc(meet_name)} &mdash; Coach Recording Sheet</h1>',
             f'    <div class="sub">Session {sess_num} &middot; {esc(date_label)} &middot; {esc(club)}</div>',
             f'    <div class="meta">{esc(course_lbl)} &middot; {esc(venue)} &middot; {ev_range}{splits_note}'
             f' &middot; entry times shown; write heat, achieved time, splits &amp; comments.</div>',
             f'  </header>']

    for ev in events:
        sw_sorted = sort_swimmers(ev['swimmers'])
        n_splits = ev['distance'] // pool_len if ev['distance'] > pool_len else 0
        splits_tag = f' &middot; {n_splits} &times; {pool_len}m' if n_splits else ''
        parts.append(f'  <section class="event">')
        parts.append(f'    <div class="ehead">')
        parts.append(f'      <div class="enum">Event {ev["eventNum"]}</div>')
        parts.append(f'      <div class="etitle">{ev["gender"]} &middot; {ev["distance"]}m {stroke_disp(ev["stroke"])}</div>')
        n_sw = len(ev['swimmers'])
        parts.append(f'      <div class="emeta">{n_sw} swimmer{"s" if n_sw!=1 else ""}{splits_tag}</div>')
        parts.append(f'    </div>')
        for sw in sw_sorted:
            parts.append(gen_swimmer(sw, ev['eventNum'], ev['distance'], pool_len))
        parts.append(f'  </section>')

    parts.append('</div></body></html>')
    return '\n'.join(parts)

# ── SESSION DATE PROMPTS ───────────────────────────────────────────────────────

DAYS = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
MONTHS = ['January','February','March','April','May','June',
          'July','August','September','October','November','December']

def prompt_date(label):
    print(f"\n  {label}")
    print("  Enter date (e.g. 31 05 2026) or press Enter to skip: ", end='', flush=True)
    val = input().strip()
    if not val: return ''
    parts = val.split()
    if len(parts) == 3:
        try:
            import datetime
            d = datetime.date(int(parts[2]), int(parts[1]), int(parts[0]))
            return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month-1]} {d.year}"
        except: pass
    return val

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    # Find PDF
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
    else:
        # Look in Downloads
        downloads = Path.home() / 'Downloads'
        pdfs = sorted(downloads.glob('*.pdf'), key=os.path.getmtime, reverse=True)
        if not pdfs:
            print("No PDF found. Usage: python3 generate.py /path/to/entries.pdf")
            sys.exit(1)
        print(f"Found PDFs in Downloads:")
        for i, p in enumerate(pdfs[:5]):
            print(f"  {i+1}. {p.name}")
        print("Enter number (or press Enter for most recent): ", end='', flush=True)
        choice = input().strip()
        idx = (int(choice) - 1) if choice.isdigit() else 0
        pdf_path = str(pdfs[idx])

    print(f"\nReading: {pdf_path}")
    lines = extract_text(pdf_path)
    print(f"  {len(lines)} text lines extracted")

    meet_name, course, swimmers = parse(lines)
    print(f"  Meet: {meet_name or '(unknown)'}")
    print(f"  Course: {course}")
    print(f"  Swimmers: {len(swimmers)}")

    raw_count = sum(len(EVT_RE.findall(l)) for l in lines)
    attributed = sum(len(s['events']) for s in swimmers)
    if attributed != raw_count:
        print(f"\n  ⚠️  WARNING: the PDF contains {raw_count} event entries but only "
              f"{attributed} made it onto the sheets.")
        print(f"  Some swimmers may be missing — please double-check the sheets "
              f"against the entries list before the meet!")
    else:
        print(f"  All {raw_count} entries accounted for ✓")

    if not swimmers:
        print("\nERROR: No swimmer entries found. Is this the right file?")
        print("Need the entries PDF with lines like: Smith, John #5A (d1/t1): B 12-12 200 Free")
        sys.exit(1)

    sessions = organise(swimmers)
    sorted_sessions = sorted(sessions.items())
    print(f"  Sessions: {[s for s,_ in sorted_sessions]}")

    # Get meet details
    print(f"\nMeet name [{meet_name}]: ", end='', flush=True)
    mn_input = input().strip()
    if mn_input: meet_name = mn_input

    print("Club name [Bridgwater ASC]: ", end='', flush=True)
    club = input().strip() or 'Bridgwater ASC'

    print("Venue (e.g. Millfield School Pool): ", end='', flush=True)
    venue = input().strip()

    # Per-session dates
    print("\nSession dates (optional — press Enter to skip):")
    session_labels = {}
    seen_days = {}
    for sess_num, sd in sorted_sessions:
        day = sd['day']
        time_opts = ['Morning','Afternoon','Evening']
        day_sessions = [s for s,d in sorted_sessions if d['day']==day]
        idx_in_day = day_sessions.index(sess_num)
        default_time = time_opts[idx_in_day] if idx_in_day < len(time_opts) else 'Afternoon'
        if day not in seen_days:
            date_str = prompt_date(f"Day {day} date")
            seen_days[day] = date_str
        else:
            date_str = seen_days[day]
        print(f"  Session {sess_num} time [{default_time}]: ", end='', flush=True)
        t = input().strip() or default_time
        if date_str:
            session_labels[sess_num] = f"{date_str} ({t})"
        else:
            session_labels[sess_num] = f"({t})"

    # Output folder
    out_dir = Path.home() / 'Desktop' / 'ObSheets'
    out_dir.mkdir(parents=True, exist_ok=True)

    slug = re.sub(r'[^A-Za-z0-9]+', '_', meet_name).strip('_') or 'Meet'
    generated = []

    for sess_num, sd in sorted_sessions:
        label = session_labels.get(sess_num, f'Session {sess_num}')
        html = gen_session(sess_num, sd, meet_name, club, venue, course, label)
        fname = out_dir / f"{slug}_Session{sess_num}.html"
        fname.write_text(html, encoding='utf-8')
        n_entries = sum(len(e['swimmers']) for e in sd['events'].values())
        print(f"  ✓ Session {sess_num}: {len(sd['events'])} events, {n_entries} entries → {fname.name}")
        generated.append(str(fname))

    print(f"\nDone! {len(generated)} file(s) saved to: {out_dir}")
    print("Open each file in your browser and print (File → Print → Save as PDF).\n")

    # Open the folder in Finder
    os.system(f'open "{out_dir}"')

if __name__ == '__main__':
    main()
