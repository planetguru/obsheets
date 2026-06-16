# Observation Sheets

A pure-Python web app for Bridgwater ASC. Upload a gala's **Confirmed Entries**
file (and optionally the **Meet pack**) and it generates a print-ready PDF of
coach observation sheets — one page set per session, every swimmer ordered
slowest-first (so the earliest heat is at the top), with blank boxes for heat,
time, splits and comments.

No AI and no external API calls — all parsing is done in Python with
`pdfplumber`, so it runs on a basic server with **zero per-use cost**.

## What it does

- Reads several entry formats automatically (Hy-Tek "All Events", the GoMotion
  "Meet Entry Report" styles, and the committed-athletes `(d1/t2)` export).
- Reads the meet pack for the **session structure** and **pool length**
  (Long Course = 50m, Short Course = 25m). Falls back to the `(d/t)` tags in the
  entries, then to a single session, if the pack doesn't spell it out — and says
  so on the result.
- **Splits**: one box per pool length, labelled cumulatively (50, 100, 150 …);
  no splits row for a race of a single length.
- **Order**: slowest entry time first, `NT` at the very top, ties by surname then
  first name.
- Verifies that every entry it reads ends up on the sheet.

## Run locally (Mac)

Double-click `ObservationSheets.command`, or:

```sh
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python app.py        # http://127.0.0.1:8000
```

## Deploy on a Linode / Ubuntu server

```sh
sudo apt update && sudo apt install -y python3-venv
git clone <your repo>  # or copy this autoobs/ folder to the server
cd autoobs
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# Run it (one worker + threads so background generation shares state):
venv/bin/gunicorn -w 1 --threads 8 -b 0.0.0.0:8000 app:app
```

To keep it running, use the included `obsheets.service` systemd unit:

```sh
sudo cp obsheets.service /etc/systemd/system/
sudo sed -i "s#/opt/autoobs#$(pwd)#g" /etc/systemd/system/obsheets.service
sudo systemctl enable --now obsheets
```

Put nginx in front for HTTPS if exposing it publicly. Generated PDFs and the
job index live in `data/` (back this folder up if you want history to persist).

## Re-run the reliability check

```sh
venv/bin/python verify.py /path/to/sample-galas
```

Parses every sample gala, confirms the parsed entry count matches an independent
raw count of the source file (nothing dropped), and renders each PDF.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Flask single-page web app (upload → generate → download) |
| `parse.py` | Pure-Python entries + meet-pack parser |
| `pdfgen.py` | PDF generator (stdlib only — draws the sheet directly) |
| `verify.py` | Reliability gate across the sample galas |
