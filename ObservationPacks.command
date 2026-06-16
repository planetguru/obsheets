#!/bin/bash
# Observation Packs — double-click to start the web app locally.
# Your browser opens automatically; keep this window open while you work.
export PATH="/opt/homebrew/bin:$PATH"
cd "$(dirname "$0")/webapp"
if [ ! -d .next ]; then
  echo "First run — building the app (takes a minute)..."
  npx next build
fi
(sleep 2 && open http://localhost:3000) &
npx next start -p 3000
