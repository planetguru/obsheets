#!/bin/bash
# Observation Sheets — double-click to start the app locally.
# Your browser opens automatically; keep this window open while you work.
cd "$(dirname "$0")/autoobs"
if [ ! -d venv ]; then
  echo "First run — setting up (one minute)…"
  python3 -m venv venv
  venv/bin/pip install -q -r requirements.txt
fi
(sleep 2 && open http://127.0.0.1:8000) &
PORT=8000 venv/bin/python app.py
echo ""
echo "Press Enter to close…"
read
