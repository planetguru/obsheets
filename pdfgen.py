"""
ObSheets PDF generator — draws coach recording sheets straight to PDF.
Pure standard library (no installs). Layout mirrors the HTML sheets:
navy/blue headers, white writable boxes for heat / time / splits / comments.
"""
import zlib, math

# ── PAGE GEOMETRY (A4 portrait, points) ──────────────────────────────────────
W, H = 595.28, 841.89
M = 34                      # page margin
CW = W - 2 * M              # content width

# ── COLOURS (match the HTML CSS variables) ───────────────────────────────────
INK    = (0.063, 0.141, 0.247)   # #10243f
ACCENT = (0.039, 0.333, 0.549)   # #0a558c
LINE   = (0.624, 0.698, 0.776)   # #9fb2c6
SOFT   = (0.933, 0.953, 0.973)   # #eef3f8
GRAY   = (0.357, 0.431, 0.518)   # #5b6e84
LGRAY  = (0.455, 0.533, 0.627)   # #7488a0
RULE   = (0.867, 0.902, 0.937)   # #dde6ef comment ruling

# Helvetica advance widths (per mille) for ASCII 32–126
_HW = [278,278,355,556,556,889,667,191,333,333,389,584,278,333,278,278,
       556,556,556,556,556,556,556,556,556,556,278,278,584,584,584,556,
       1015,667,667,722,722,667,611,778,722,278,500,667,556,833,722,778,
       667,778,722,667,611,722,667,944,667,667,611,278,278,278,469,556,
       333,556,556,500,556,556,278,556,556,222,222,500,222,833,556,556,
       556,556,333,500,278,556,500,722,500,500,500,334,260,334,584]

def text_w(s, size, bold=False):
    w = sum(_HW[ord(c) - 32] if 32 <= ord(c) <= 126 else 556 for c in s)
    return w * size / 1000 * (1.08 if bold else 1.0)

STROKE_NAMES = {'Back': 'Backstroke', 'Breast': 'Breaststroke', 'Free': 'Freestyle',
                'Fly': 'Butterfly', 'Medley': 'IM', 'IM': 'IM'}

# ── LOW-LEVEL PDF WRITER ──────────────────────────────────────────────────────

class Doc:
    """Minimal PDF document. y-coordinates are measured from the TOP of the page."""
    def __init__(self):
        self.pages = []
        self.cur = None

    def page(self):
        self.cur = []
        self.pages.append(self.cur)

    # WinAnsi codepoints for characters latin-1 lacks (the font encoding is WinAnsi)
    _WINANSI = str.maketrans({'—': '\x97', '–': '\x96', '‘': '\x91',
                              '’': '\x92', '“': '\x93', '”': '\x94',
                              '…': '\x85'})

    def text(self, x, y, s, size=10, bold=False, color=INK):
        s = str(s).translate(self._WINANSI).encode('latin-1', 'replace').decode('latin-1')
        esc = s.replace('\\', r'\\').replace('(', r'\(').replace(')', r'\)')
        f = 'F2' if bold else 'F1'
        r, g, b = color
        self.cur.append(f"BT /{f} {size} Tf {r:.3f} {g:.3f} {b:.3f} rg "
                        f"{x:.2f} {H - y:.2f} Td ({esc}) Tj ET")

    def _round_path(self, x, yy, w, h, r):
        k = 0.5523 * r
        return (f"{x+r:.2f} {yy:.2f} m {x+w-r:.2f} {yy:.2f} l "
                f"{x+w-r+k:.2f} {yy:.2f} {x+w:.2f} {yy+r-k:.2f} {x+w:.2f} {yy+r:.2f} c "
                f"{x+w:.2f} {yy+h-r:.2f} l "
                f"{x+w:.2f} {yy+h-r+k:.2f} {x+w-r+k:.2f} {yy+h:.2f} {x+w-r:.2f} {yy+h:.2f} c "
                f"{x+r:.2f} {yy+h:.2f} l "
                f"{x+r-k:.2f} {yy+h:.2f} {x:.2f} {yy+h-r+k:.2f} {x:.2f} {yy+h-r:.2f} c "
                f"{x:.2f} {yy+r:.2f} l "
                f"{x:.2f} {yy+r-k:.2f} {x+r-k:.2f} {yy:.2f} {x+r:.2f} {yy:.2f} c ")

    def rect(self, x, y, w, h, stroke=None, fill=None, lw=1.0, r=0):
        yy = H - y - h
        ops = ''
        if fill:
            ops += f"{fill[0]:.3f} {fill[1]:.3f} {fill[2]:.3f} rg "
        if stroke:
            ops += f"{stroke[0]:.3f} {stroke[1]:.3f} {stroke[2]:.3f} RG {lw:.2f} w "
        if r > 0:
            ops += self._round_path(x, yy, w, h, r) + 'h '
        else:
            ops += f"{x:.2f} {yy:.2f} {w:.2f} {h:.2f} re "
        ops += 'B' if (stroke and fill) else ('f' if fill else 'S')
        self.cur.append(ops)

    def hline(self, x1, x2, y, color=LINE, lw=0.8):
        r, g, b = color
        self.cur.append(f"{r:.3f} {g:.3f} {b:.3f} RG {lw:.2f} w "
                        f"{x1:.2f} {H - y:.2f} m {x2:.2f} {H - y:.2f} l S")

    def build(self):
        objs = []   # (num, bytes) in order; numbers assigned below
        n_pages = len(self.pages)
        # 1 catalog, 2 pages-tree, 3 F1, 4 F2, then per page: page obj, content obj
        kids = ' '.join(f"{5 + i * 2} 0 R" for i in range(n_pages))
        objs.append(b"<</Type/Catalog/Pages 2 0 R>>")
        objs.append(f"<</Type/Pages/Kids[{kids}]/Count {n_pages}>>".encode())
        objs.append(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>")
        objs.append(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica-Bold/Encoding/WinAnsiEncoding>>")
        for i, page in enumerate(self.pages):
            cnum = 6 + i * 2
            objs.append(f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 {W} {H}]"
                        f"/Resources<</Font<</F1 3 0 R/F2 4 0 R>>>>"
                        f"/Contents {cnum} 0 R>>".encode())
            stream = zlib.compress('\n'.join(page).encode('latin-1'))
            objs.append(b"<</Filter/FlateDecode/Length " + str(len(stream)).encode()
                        + b">>\nstream\n" + stream + b"\nendstream")
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(objs):
            offsets.append(len(out))
            out += f"{i + 1} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
        for off in offsets:
            out += f"{off:010d} 00000 n \n".encode()
        out += (f"trailer\n<</Size {len(objs) + 1}/Root 1 0 R>>\n"
                f"startxref\n{xref}\n%%EOF").encode()
        return bytes(out)

# ── SHEET LAYOUT ──────────────────────────────────────────────────────────────

PAD = 10          # padding inside a swimmer box
ROW1 = 18         # name + heat/entry/time row height
SPLIT_W, SPLIT_H = 42, 21
COMMENT_H = 40
BOX_GAP = 8       # gap between swimmer boxes
EVH = 32          # event header height

def _splits_layout(distance, pool_len):
    """Return (n_boxes, per_row, rows) for the splits grid, or (0,0,0)."""
    if distance <= pool_len:
        return 0, 0, 0
    n = distance // pool_len
    label_w = text_w(f"{pool_len}m splits", 7) + 8
    per_row = max(1, int((CW - 2 * PAD - label_w) // (SPLIT_W + 5)))
    return n, per_row, math.ceil(n / per_row)

def _box_height(distance, pool_len):
    n, _, rows = _splits_layout(distance, pool_len)
    h = PAD + ROW1
    if n:
        h += 7 + rows * (8 + SPLIT_H + 4)
    h += 8 + 9 + COMMENT_H + PAD
    return h

def _field(d, x_right, y, label, box_w, value=None):
    """Draw a label + box pair ending at x_right; return x of label start."""
    bx = x_right - box_w
    if value is not None:
        d.rect(bx, y, box_w, ROW1, stroke=LINE, fill=SOFT, lw=0.8, r=3)
        d.text(bx + (box_w - text_w(value, 9.5, True)) / 2, y + 13, value,
               9.5, bold=True, color=INK)
    else:
        d.rect(bx, y, box_w, ROW1, stroke=INK, lw=0.9, r=3)
    lw_ = text_w(label, 6.3, True)
    d.text(bx - lw_ - 5, y + 12.5, label, 6.3, bold=True, color=GRAY)
    return bx - lw_ - 5

def _swimmer_box(d, y, sw, ev_num, distance, pool_len):
    h = _box_height(distance, pool_len)
    x = M
    d.rect(x, y, CW, h, stroke=LINE, lw=1.1, r=6)
    cy = y + PAD

    # Row 1 — fields drawn right-to-left, then the name in the remaining space
    xr = x + CW - PAD
    xr = _field(d, xr, cy, 'TIME', 66) - 12
    entry = sw.get('entryTime') or 'NT'
    xr = _field(d, xr, cy, 'ENTRY', 60, value=entry) - 12
    xr = _field(d, xr, cy, 'HEAT', 44) - 12

    nx = x + PAD
    tag = f"#{ev_num}"
    d.text(nx, cy + 13, tag, 7, bold=True, color=LGRAY)
    nx += text_w(tag, 7, True) + 6
    name = f"{sw['firstname']} {sw['surname']}"
    d.text(nx, cy + 13.5, name, 11.5, bold=True, color=INK)
    nx += text_w(name, 11.5, True) + 5
    if sw.get('age') is not None:
        d.text(nx, cy + 13.5, f"({sw['age']})", 9.5, color=GRAY)
    cy += ROW1 + 7

    # Splits grid
    n, per_row, rows = _splits_layout(distance, pool_len)
    if n:
        lab = f"{pool_len}m splits"
        d.text(x + PAD, cy + 8 + SPLIT_H - 3, lab.upper(), 6.3, bold=True, color=GRAY)
        gx0 = x + PAD + text_w(lab, 7) + 10
        for i in range(n):
            r_, c_ = divmod(i, per_row)
            bx = gx0 + c_ * (SPLIT_W + 5)
            by = cy + r_ * (8 + SPLIT_H + 4)
            d.text(bx + (SPLIT_W - text_w(str((i + 1) * pool_len), 6.3)) / 2,
                   by + 6, str((i + 1) * pool_len), 6.3, color=LGRAY)
            d.rect(bx, by + 8, SPLIT_W, SPLIT_H, stroke=INK, lw=0.9, r=3)
        cy += rows * (8 + SPLIT_H + 4)
    cy += 8

    # Comments
    d.text(x + PAD, cy + 6, "COACH'S COMMENTS", 6.3, bold=True, color=GRAY)
    cy += 9
    d.rect(x + PAD, cy, CW - 2 * PAD, COMMENT_H, stroke=INK, lw=0.9, r=4)
    d.hline(x + PAD + 4, x + CW - PAD - 4, cy + COMMENT_H / 2, color=RULE, lw=0.8)
    return h

def _event_header(d, y, ev, pool_len, cont=False):
    d.rect(M, y, CW, EVH, stroke=ACCENT, lw=1.6, r=6)
    ty = y + EVH / 2 + 4.5
    x = M + 12
    label = f"Event {ev['eventNum']}" + ("  (continued)" if cont else "")
    d.text(x, ty, label, 13, bold=True, color=ACCENT)
    x += text_w(label, 13, True) + 14
    title = f"{ev['gender']}  ·  {ev['distance']}m {STROKE_NAMES.get(ev['stroke'], ev['stroke'])}"
    d.text(x, ty, title, 11.5, bold=True, color=ACCENT)
    n = len(ev['swimmers'])
    n_splits = ev['distance'] // pool_len if ev['distance'] > pool_len else 0
    meta = f"{n} swimmer{'s' if n != 1 else ''}"
    if n_splits:
        meta += f"  ·  {n_splits} × {pool_len}m"
    d.text(M + CW - 12 - text_w(meta, 8.5), ty - 0.5, meta, 8.5, color=GRAY)
    return EVH

def _session_cover(d, y, sess_num, meet_name, club, venue, course, date_label, ev_range, pool_len):
    h = 64
    d.rect(M, y, CW, h, stroke=INK, fill=(1, 1, 1), lw=1.8, r=8)
    d.text(M + 14, y + 20, f"{meet_name} — Coach Recording Sheet", 13.5, bold=True, color=INK)
    d.text(M + 14, y + 36, f"Session {sess_num}  ·  {date_label}  ·  {club}", 10.5,
           bold=True, color=ACCENT)
    course_lbl = f"{'Long' if course == 'long' else 'Short'} Course ({pool_len}m)"
    meta = f"{course_lbl}  ·  {venue}  ·  {ev_range}  ·  entry times shown; write heat, time, splits & comments"
    d.text(M + 14, y + 52, meta, 8, color=GRAY)
    return h

def add_session(d, sess_num, sess_data, meet_name, club, venue, course, date_label):
    pool_len = 50 if course == 'long' else 25
    events = sorted(sess_data['events'].values(), key=lambda e: e['eventNum'])
    ev_nums = [e['eventNum'] for e in events]
    ev_range = f"Events {min(ev_nums)}–{max(ev_nums)}" if ev_nums else ''
    bottom = H - M - 14   # leave room for the footer line
    pageno = 0

    def footer():
        s = f"Session {sess_num}  ·  page {pageno}"
        d.text(M + CW - text_w(s, 7.5), H - M + 6, s, 7.5, color=LGRAY)

    from generate import sort_swimmers   # same ordering rules as the HTML sheets
    first = True
    for ev in events:
        d.page(); pageno += 1; footer()
        y = M
        if first:
            y += _session_cover(d, y, sess_num, meet_name, club, venue, course,
                                date_label, ev_range, pool_len) + 12
            first = False
        y += _event_header(d, y, ev, pool_len) + 10
        for sw in sort_swimmers(ev['swimmers']):
            bh = _box_height(ev['distance'], pool_len)
            if y + bh > bottom:
                d.page(); pageno += 1; footer()
                y = M
                y += _event_header(d, y, ev, pool_len, cont=True) + 10
            _swimmer_box(d, y, sw, ev['eventNum'], ev['distance'], pool_len)
            y += bh + BOX_GAP

def session_pdf(sess_num, sess_data, meet_name, club, venue, course, date_label):
    d = Doc()
    add_session(d, sess_num, sess_data, meet_name, club, venue, course, date_label)
    return d.build()

def meet_pdf(sessions, meet_name, club, venue, course, labels):
    """sessions: list of (sess_num, sess_data); labels: {sess_num: date_label}."""
    d = Doc()
    for sn, sd in sessions:
        add_session(d, sn, sd, meet_name, club, venue, course, labels.get(sn, ''))
    return d.build()
