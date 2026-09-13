#!/bin/bash
# B2B Outbound OS - start on macOS / Linux
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] Python 3 is not installed."
  echo "Install Python 3.10 from https://www.python.org/downloads/"
  exit 1
fi

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 10) else 1)'; then
  V=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null)
  echo "[ERROR] Python 3.10 is required. You have Python ${V:-?}."
  echo "Install 3.10 from https://www.python.org/downloads/ (keep 3.10 installed; other versions are not supported)."
  exit 1
fi

if [ ! -f ".env" ]; then
  cp .env.example .env
fi

if [ ! -d "venv" ]; then
  echo "First run: creating Python environment (one time)..."
  python3 -m venv venv
  source venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
else
  source venv/bin/activate
fi

PORT=$(grep -E '^PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d ' ')
PORT=${PORT:-8010}
echo "B2B Outbound OS running at http://localhost:$PORT  (Ctrl+C to stop)"
python main.py

