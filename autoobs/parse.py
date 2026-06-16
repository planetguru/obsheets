"""
Pure-Python parser for swimming-gala observation sheets.

Two inputs per meet:
  - Confirmed Entries: who swims what, with ages and entry times.
  - Meet pack: session structure + pool length (Long/Short course).

The event NUMBER is the join key. Entries give swimmers+times+event descriptions;
the meet pack gives which session each event belongs to and the pool length.

No AI / no network. Text is extracted with pdfplumber (pdfminer.six under the
hood) — pure Python, installs with pip, no system binaries.
"""
from __future__ import annotations
import re
from collections import defaultdict
from dataclasses import dataclass, field

import pdfplumber

# ── PDF TEXT ──────────────────────────────────────────────────────────────────

def extract_text(path: str) -> str:
    out = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text(x_tolerance=1.5, y_tolerance=3) or ""
                out.append(t)
    except Exception:
        raise ValueError(
            "That file couldn't be opened as a PDF. Please upload a PDF document.")
    text = "\n".join(out)
    # Normalise curly apostrophes/quotes so names like O'Brien parse and display cleanly
    return text.replace("’", "'").replace("‘", "'").replace("ʼ", "'")


def lines_of(text: str) -> list[str]:
    return [l.rstrip() for l in text.split("\n")]


# ── NORMALISATION ─────────────────────────────────────────────────────────────

STROKE_CANON = {
    "free": "Free", "freestyle": "Free",
    "back": "Back", "backstroke": "Back",
    "breast": "Breast", "breaststroke": "Breast",
    "fly": "Fly", "butterfly": "Fly",
    "im": "IM", "medley": "IM", "individualmedley": "IM",
}


def canon_stroke(s: str) -> str:
    key = re.sub(r"[^a-z]", "", s.lower())
    return STROKE_CANON.get(key, s.strip().title())


def canon_gender(s: str) -> str:
    low = s.lower()
    if "mixed" in low:
        return "Mixed"
    if "girl" in low or "female" in low or re.search(r"\bg\b", low) or low.strip() == "g":
        return "Girls"
    if "boy" in low or "male" in low or "open" in low or low.strip() == "b":
        return "Boys"
    return "Mixed"


def clean_time(t: str) -> str:
    """Pull the time token out of blobs like '1:20.50L Approved' or '42.18S'."""
    t = t.strip()
    if "NT" in t.upper().split() or t.upper() == "NT":
        return "NT"
    m = re.match(r"\d[\d:.]*", t)
    return m.group(0).rstrip(".") if m else t


def time_suffix(t: str) -> str | None:
    """Course letter that sits right after the time digits (L=long, S=short)."""
    m = re.search(r"\d\s*([LSls])\b", t)
    return m.group(1).upper() if m else None


def age_floor(group: str) -> int | None:
    """Lower bound of an age band: '14-14'->14, '17 & Over'->17, '16-99'->16."""
    m = re.search(r"\d+", group)
    return int(m.group(0)) if m else None


# ── DATA MODEL ────────────────────────────────────────────────────────────────

@dataclass
class Entry:
    event_num: int
    gender: str
    distance: int
    stroke: str
    entry_time: str
    session_tag: int | None = None  # from (dD/tT) when present


@dataclass
class Swimmer:
    first: str
    surname: str
    age: int | None
    entries: list[Entry] = field(default_factory=list)


@dataclass
class ParsedEntries:
    meet_name: str
    dates: str
    swimmers: list[Swimmer]
    course_hint: int | None  # 50 / 25 from time suffixes, else None


# ── ENTRIES PARSING ───────────────────────────────────────────────────────────

# Family 3: committed-athletes event  e.g.
#   #106F (d1/t1): G 14-14 200 Fly (2:56.70L)   /  #17H (d2/t3): B 16-99 200 Medley (3:40.60L Approved)
#   #104I (d1/t1): G 17 & Over 100 Free (1:10.50L)   (age group is free-form, may contain a number)
RE_DT_EVENT = re.compile(
    r"#(\d+)[A-Za-z]*\s*\(\s*d(\d+)\s*/\s*t(\d+)\s*\)\s*:\s*([BGMbgm])\s+"
    r"(.+?)\s+(\d+)\s+([A-Za-z]+)\s*\(\s*([^)]+?)\s*\)"
)  # groups: 1=num 2=day 3=timeline 4=gender 5=ageband 6=distance 7=stroke 8=time

# Family 1: Hy-Tek "All Events" event  e.g.  #1 Mixed 400 IM 8:15.00 1/4
RE_HYTEK_EVENT = re.compile(
    r"#(\d+)\s+([A-Za-z/]+)\s+(\d+)\s+([A-Za-z]+)\s+(NT|[\d:.]+)\s+\d+\s*/\s*\d+"
)
RE_HYTEK_SWIMMER = re.compile(
    r"^\s*\d+\s+(.+?)\s+-\s+(Male|Female)\s+-\s+Age:\s*(\d+)\s+-\s+Ind/Rel", re.I
)

# Family 2: plain Meet Entry Report event  e.g.
#   # 2 Open/Boy Open 50 Fly 42.18S   /  # 19E Girl 13-13 50 Fly 39.60L
RE_PLAIN_EVENT = re.compile(
    r"^#\s*(\d+)[A-Za-z]*\s+(.*?)\s+(\d+)\s+([A-Za-z]+)\s+(NT|[\d:.]+)([SLsl]?)\s*$"
)
# Family 2 swimmer line:  Surname, First Middle (12)
RE_PLAIN_SWIMMER = re.compile(r"^([A-Z][^#()]+?,\s*[^#()]+?)\s*\((\d+)\)\s*$")

NOISE_NAME = re.compile(r"meet|entry|report|date|location|page|hy-tek|club|programme", re.I)


def split_name(full: str) -> tuple[str, str]:
    """'Surname, First Middle' -> (first, surname). Falls back gracefully."""
    full = full.strip()
    if "," in full:
        sur, rest = full.split(",", 1)
        rest = rest.strip()
        # first name = first token; drop middle names/initials for display
        first = rest.split()[0] if rest.split() else rest
        return first, sur.strip()
    parts = full.split()
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return full, ""


def _meet_name_dates(text: str) -> tuple[str, str]:
    name, dates = "", ""
    m = re.search(r"Meet Info:\s*(.+)", text)
    if m:
        name = m.group(1).strip()
        # GoMotion sometimes wraps a trailing year onto the next line
        nxt = text[m.end():m.end() + 60].lstrip("\n").splitlines()
        if nxt and re.fullmatch(r"\s*\d{4}\s*", nxt[0]):
            name = f"{name} {nxt[0].strip()}"
    if not name:
        m = re.search(r"Meet:\s*(.+?)(?:\s*\(Location|$)", text)
        if m:
            name = m.group(1).strip()
    if not name:
        # Hy-Tek header: line with a date range
        m = re.search(r"^(.*\b\d{4}\b.*?)\s*-\s*\d{2}/\d{2}/\d{4}", text, re.M)
        if m:
            name = m.group(1).strip()
    md = re.search(r"Date:\s*([^\n(]+)", text) or re.search(r"(\d{2}/\d{2}/\d{4}\s*(?:to|-)\s*\d{2}/\d{2}/\d{4})", text)
    if md:
        dates = md.group(1).strip()
    return name, dates


def parse_entries(text: str) -> ParsedEntries:
    lines = lines_of(text)
    meet_name, dates = _meet_name_dates(text)

    has_dt = bool(RE_DT_EVENT.search(text))
    is_hytek = bool(re.search(r"Team Entries|All Events|-\s*(Male|Female)\s*-\s*Age:", text))

    swimmers: list[Swimmer] = []
    suffixes: list[str] = []

    if has_dt:
        swimmers, suffixes = _parse_dt(lines)
    elif is_hytek:
        swimmers, suffixes = _parse_hytek(lines)
    else:
        swimmers, suffixes = _parse_plain(lines)

    course_hint = None
    if suffixes:
        L = suffixes.count("L")
        S = suffixes.count("S")
        if L or S:
            course_hint = 50 if L >= S else 25

    swimmers = [s for s in swimmers if s.entries]
    return ParsedEntries(meet_name, dates, swimmers, course_hint)


def _add_entry(sw: Swimmer, num, gender, dist, stroke, time, suffixes, tag=None):
    if any(e.event_num == num for e in sw.entries):
        return
    suf = time_suffix(time)
    if suf:
        suffixes.append(suf)
    sw.entries.append(Entry(num, canon_gender(gender), int(dist),
                            canon_stroke(stroke), clean_time(time), tag))


RE_NAME_WITH_COMMA = re.compile(r"^[A-Z][A-Za-z'\-]+,")
RE_BARE_WORD = re.compile(r"^[A-Z][A-Za-z'\-]+$")


def _parse_dt(lines: list[str]):
    swimmers: list[Swimmer] = []
    suffixes: list[str] = []
    cur: Swimmer | None = None
    pending_surname: str | None = None  # saw "Surname," on its own line

    def start_swimmer(first: str, surname: str) -> Swimmer:
        nonlocal cur
        cur = Swimmer(first, surname, None)
        swimmers.append(cur)
        return cur

    for line in lines:
        events = list(RE_DT_EVENT.finditer(line))
        if events:
            m = events[0]
            prefix = line[:m.start()].strip()
            if cur is not None and cur.surname.endswith("-") and prefix \
                    and not NOISE_NAME.search(prefix):
                # second half of a hyphenated surname ("Lacy-" then "Hulbert,")
                if "," in prefix:
                    rest, after = prefix.split(",", 1)
                    cur.surname += rest.strip()
                    if after.strip():
                        cur.first = after.strip().split()[0]
                else:
                    cur.surname += prefix.strip()
            elif prefix and prefix.endswith("-") and not NOISE_NAME.search(prefix) \
                    and RE_BARE_WORD.match(prefix):
                # first half of a hyphenated surname; rest + first name follow
                start_swimmer("", prefix)
                pending_surname = None
            elif prefix and "," in prefix and not NOISE_NAME.search(prefix):
                # "Surname, First ..." or "Surname," (first name wraps to next line)
                first, sur = split_name(prefix)
                start_swimmer(first, sur)
                pending_surname = None
            elif pending_surname is not None:
                # previous line was a bare "Surname,"; this line's prefix is the first name
                first = prefix if (prefix and RE_BARE_WORD.match(prefix)) else ""
                start_swimmer(first, pending_surname)
                pending_surname = None
            elif prefix and RE_BARE_WORD.match(prefix) and cur is not None and not cur.first:
                # wrapped first name for the current swimmer ("Surname," then "First #ev")
                cur.first = prefix
            for me in events:
                if cur is not None:
                    if cur.age is None:
                        cur.age = age_floor(me.group(5))
                    _add_entry(cur, int(me.group(1)), me.group(4), me.group(6),
                               me.group(7), me.group(8), suffixes, int(me.group(3)))
            continue

        stripped = line.strip()
        # A bare wrapped first name for a swimmer still missing one
        if RE_BARE_WORD.match(stripped) and cur is not None and not cur.first \
                and not NOISE_NAME.search(stripped):
            cur.first = stripped
            continue
        # A bare "Surname," (first name / events on following lines)
        if RE_NAME_WITH_COMMA.match(stripped) and not NOISE_NAME.search(stripped) \
                and len(stripped) < 40:
            first, sur = split_name(stripped)
            if first:  # "Surname, First" with no event on the line
                start_swimmer(first, sur)
                pending_surname = None
            else:
                pending_surname = sur
    return swimmers, suffixes


def _parse_hytek(lines: list[str]):
    swimmers: list[Swimmer] = []
    suffixes: list[str] = []
    cur: Swimmer | None = None
    for line in lines:
        ms = RE_HYTEK_SWIMMER.match(line)
        if ms:
            first, sur = split_name(ms.group(1))
            cur = Swimmer(first, sur, int(ms.group(3)))
            swimmers.append(cur)
            continue
        if cur is not None:
            for me in RE_HYTEK_EVENT.finditer(line):
                _add_entry(cur, int(me.group(1)), me.group(2), me.group(3),
                           me.group(4), me.group(5), suffixes)
    return swimmers, suffixes


def _parse_plain(lines: list[str]):
    swimmers: list[Swimmer] = []
    suffixes: list[str] = []
    cur: Swimmer | None = None
    for line in lines:
        ms = RE_PLAIN_SWIMMER.match(line)
        if ms and not NOISE_NAME.search(ms.group(1)):
            first, sur = split_name(ms.group(1))
            cur = Swimmer(first, sur, int(ms.group(2)))
            swimmers.append(cur)
            continue
        me = RE_PLAIN_EVENT.match(line.strip())
        if me and cur is not None:
            gender_blob = me.group(2)
            _add_entry(cur, int(me.group(1)), gender_blob, me.group(3),
                       me.group(4), me.group(5) + me.group(6), suffixes)
    return swimmers, suffixes


# ── MEET PACK PARSING ─────────────────────────────────────────────────────────

@dataclass
class ParsedPack:
    meet_name: str
    venue: str
    dates: str
    pool_length: int | None
    event_session: dict[int, int]
    session_labels: dict[int, str]


RE_POOL_M = re.compile(r"pool\s+is\s+(\d+)\s*m", re.I)
RE_COURSE_WORD = re.compile(r"\b(long|short)\s+course\b", re.I)
RE_SESSION_HDR = re.compile(r"\bsession\s+(\d+)\b", re.I)
RE_EVENT_NUM = re.compile(r"\bevent\s+(\d+)\b", re.I)
RE_DAY = re.compile(
    r"\b((?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\s+\d{1,2}(?:st|nd|rd|th)?\s+"
    r"[A-Z][a-z]+\s+\d{4})", re.I)


def parse_meet_pack(text: str) -> ParsedPack:
    lines = lines_of(text)
    meet_name = lines[0].strip() if lines else ""
    if NOISE_NAME.search(meet_name) or len(meet_name) < 4:
        for l in lines[:8]:
            if len(l.strip()) > 6 and not NOISE_NAME.search(l):
                meet_name = l.strip()
                break
    _, dates = _meet_name_dates(text)

    pool_length = None
    mp = RE_POOL_M.search(text)
    if mp:
        pool_length = int(mp.group(1))
    else:
        mc = RE_COURSE_WORD.search(text)
        if mc:
            pool_length = 50 if mc.group(1).lower() == "long" else 25

    # Single-column "Session N ... Event N" mapping.
    event_session: dict[int, int] = {}
    session_labels: dict[int, str] = {}
    cur_session: int | None = None
    cur_day = ""
    for line in lines:
        dm = RE_DAY.search(line)
        if dm:
            cur_day = dm.group(1).strip()
        sm = RE_SESSION_HDR.search(line)
        if sm:
            # ignore prose like "each session"; require it to look like a header
            if re.match(r"^\s*session\s+\d+\s*$", line.strip(), re.I) or len(line.strip()) < 30:
                cur_session = int(sm.group(1))
                session_labels[cur_session] = cur_day
        for em in RE_EVENT_NUM.finditer(line):
            n = int(em.group(1))
            if cur_session is not None and n not in event_session:
                event_session[n] = cur_session

    venue = ""
    vm = re.search(r"Location:\s*([^)\n]+)", text)
    if vm:
        venue = vm.group(1).strip()
    return ParsedPack(meet_name, venue, dates, pool_length, event_session, session_labels)


# ── COMBINE ───────────────────────────────────────────────────────────────────

def to_seconds(t: str) -> float:
    if not t or t.upper() == "NT":
        return float("inf")
    parts = t.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except ValueError:
        return float("inf")


@dataclass
class SheetSwimmer:
    first: str
    surname: str
    age: int | None
    entry_time: str


@dataclass
class SheetEvent:
    number: int
    gender: str
    distance: int
    stroke: str
    swimmers: list[SheetSwimmer]


@dataclass
class SheetSession:
    number: int
    label: str
    events: list[SheetEvent]


@dataclass
class Meet:
    name: str
    venue: str
    dates: str
    course: str          # "long" | "short"
    pool_length: int
    sessions: list[SheetSession]
    entry_count: int
    swimmer_count: int
    warnings: list[str]


def build_meet(entries: ParsedEntries, pack: ParsedPack | None) -> Meet:
    warnings: list[str] = []

    # ── events from entries: event_num -> event details + swimmers ──
    events: dict[int, SheetEvent] = {}
    event_tag: dict[int, int] = {}   # (d/t) session from entries
    for sw in entries.swimmers:
        for e in sw.entries:
            ev = events.get(e.event_num)
            if ev is None:
                ev = SheetEvent(e.event_num, e.gender, e.distance, e.stroke, [])
                events[e.event_num] = ev
            ev.swimmers.append(SheetSwimmer(sw.first, sw.surname, sw.age, e.entry_time))
            if e.session_tag is not None:
                event_tag[e.event_num] = e.session_tag

    # ── pool length: pack -> entry time suffix -> default 50 ──
    pool_length = (pack.pool_length if pack and pack.pool_length else None) or entries.course_hint or 50
    course = "long" if pool_length >= 50 else "short"
    if pack and pack.pool_length and entries.course_hint and pack.pool_length != entries.course_hint:
        warnings.append(
            f"Meet pack says {pack.pool_length}m pool but entry times suggest "
            f"{entries.course_hint}m — using the meet pack ({pool_length}m).")

    # ── session grouping: (d/t) tags -> meet-pack map -> single session ──
    pack_map = pack.event_session if pack else {}
    if event_tag and len(event_tag) >= len(events) * 0.5:
        source = "tags"
        event_session = {n: event_tag.get(n, max(event_tag.values(), default=1)) for n in events}
    elif pack_map and sum(1 for n in events if n in pack_map) >= len(events) * 0.5:
        source = "pack"
        fallback_s = min(pack_map.values(), default=1)
        event_session = {n: pack_map.get(n, fallback_s) for n in events}
        missing = [n for n in events if n not in pack_map]
        if missing:
            warnings.append(
                f"{len(missing)} event(s) weren't found in the meet pack programme "
                f"and were placed in session {fallback_s}: {sorted(missing)}")
    else:
        source = "single"
        event_session = {n: 1 for n in events}
        if len(events) > 0 and not pack_map and not event_tag:
            warnings.append(
                "No session structure found — all events were placed in a single session.")

    # ── assemble sessions ──
    by_session: dict[int, list[SheetEvent]] = defaultdict(list)
    for n, ev in events.items():
        by_session[event_session[n]].append(ev)

    sessions: list[SheetSession] = []
    for snum in sorted(by_session):
        evs = sorted(by_session[snum], key=lambda e: e.number)
        for ev in evs:
            ev.swimmers.sort(key=lambda s: (-to_seconds(s.entry_time), s.surname, s.first))
        label = ""
        if pack and source == "pack":
            label = pack.session_labels.get(snum, "")
        sessions.append(SheetSession(snum, label, evs))

    meet_name = entries.meet_name or (pack.meet_name if pack else "") or "Swimming Meet"
    venue = (pack.venue if pack else "") or ""
    dates = entries.dates or (pack.dates if pack else "") or ""
    entry_count = sum(len(e.swimmers) for e in events.values())
    swimmer_count = len(entries.swimmers)

    return Meet(meet_name, venue, dates, course, pool_length, sessions,
                entry_count, swimmer_count, warnings)


def parse_meet(entries_path: str, pack_path: str | None) -> Meet:
    entries = parse_entries(extract_text(entries_path))
    pack = parse_meet_pack(extract_text(pack_path)) if pack_path else None
    return build_meet(entries, pack)
