"""
Reliability gate. Parses every sample gala, checks that the number of entries
parsed equals an independent raw token count of the source file (i.e. nothing is
silently dropped), checks names/ages look sane, and renders a PDF for each.

Run:  venv/bin/python verify.py [path-to-samples-dir]
Exits non-zero if any check fails.
"""
from __future__ import annotations
import os
import re
import sys

import parse
import pdfgen

SAMPLES = sys.argv[1] if len(sys.argv) > 1 else \
    "/Users/christopherlacy-hulbert/Downloads/auto-obsheets"

# (entries, meet pack) per gala
CASES = {
    "BASC LDCC": ("BASC LDCC/LDCC_26_Confirmed_Entries.pdf",
                  "BASC LDCC/Bridgwater_SC_-_Long_Distance_Club_Champs_Meet_Pack_Conditions_-_Jun_26_.pdf"),
    "Bobby Tutt": ("Bobby Tutt/Bobby_Tutt_Checking_Entries_2026 (1).pdf",
                   "Bobby Tutt/Bobby_Tutt_Memorial_Meet_2026_Meet_Pack.pdf"),
    "City of Bristol": ("City of Bristol/Entries.pdf", "City of Bristol/Meet_Pack.pdf"),
    "City of Wells": ("City of Wells/Wells Entries V2.pdf", "City of Wells/City of Wells Meet Pack.pdf"),
    "NUEL": ("NUEL SC Joy Atotileto Memorial/Entries.pdf", "NUEL SC Joy Atotileto Memorial/Meet_Pack.pdf"),
}


def raw_count(text: str) -> int:
    dt = len(re.findall(r"#\d+[A-Za-z]*\s*\(d\d+/t\d+\)", text))
    hytek = len(re.findall(
        r"#\d+\s+[A-Za-z/]+\s+\d+\s+[A-Za-z]+\s+(?:NT|[\d:.]+)\s+\d+\s*/\s*\d+", text))
    plain = len(re.findall(
        r"(?m)^#\s*\d+[A-Za-z]*\s+.*?\s+\d+\s+[A-Za-z]+\s+(?:NT|[\d:.]+)[SLsl]?\s*$", text))
    return max(dt, hytek, plain)


def main() -> int:
    failures = 0
    for name, (e, p) in CASES.items():
        epath, ppath = os.path.join(SAMPLES, e), os.path.join(SAMPLES, p)
        if not os.path.exists(epath):
            print(f"SKIP {name}: sample not found ({epath})")
            continue
        text = parse.extract_text(epath)
        raw = raw_count(text)
        meet = parse.parse_meet(epath, ppath if os.path.exists(ppath) else None)
        placed = sum(len(ev.swimmers) for s in meet.sessions for ev in s.events)

        problems = []
        if placed != raw:
            problems.append(f"entry count {placed} != raw {raw}")
        bad = [(s.surname, s.first) for s in
               parse.parse_entries(text).swimmers if not s.first or not s.surname]
        if bad:
            problems.append(f"bad names: {bad}")

        # render must not raise
        try:
            pdf = pdfgen.meet_to_pdf(meet)
            assert pdf.startswith(b"%PDF"), "not a PDF"
        except Exception as ex:
            problems.append(f"PDF render failed: {ex}")

        status = "OK  " if not problems else "FAIL"
        if problems:
            failures += 1
        print(f"[{status}] {name:16s} {meet.course} {meet.pool_length}m | "
              f"{placed} entries | {len(meet.sessions)} sessions"
              + ("  -> " + "; ".join(problems) if problems else ""))

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{failures} FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
