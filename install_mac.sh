#!/bin/bash
# B2B Outbound OS - one-time installer for macOS / Linux
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] Python 3 is not installed."
  echo "Install Python 3.10 from https://www.python.org/downloads/"
  exit 1
fi

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 10) else 1)'; then
  V=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null)
  echo "[ERROR] Python 3.10 is required. You have Python ${V:-?}."
  echo "Install 3.10 from https://www.python.org/downloads/ (macOS: brew install python@3.10)."
  exit 1
fi

if [ ! -d "venv" ]; then
  echo "Creating Python virtual environment..."
  python3 -m venv venv
fi

source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo ""
echo "Setup complete. Start the system with:  bash start.sh"
echo "Then open http://localhost:8010 and create your owner account."
