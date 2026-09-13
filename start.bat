@echo off
setlocal
cd /d "%~dp0"
title B2B Outbound OS

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found.
  echo Install Python 3.10 from https://www.python.org/downloads/
  echo Tick "Add python.exe to PATH", then run this file again.
  pause
  exit /b 1
)

python -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 10) else 1)"
if errorlevel 1 (
  python -c "import sys; print('You have Python ' + sys.version.split()[0])"
  echo.
  echo [ERROR] B2B Outbound OS requires Python 3.10.
  echo Download 3.10 from https://www.python.org/downloads/
  pause
  exit /b 1
)

if not exist ".env" copy ".env.example" ".env" >nul

set "PORT="
for /f "tokens=2 delims==" %%p in ('findstr /b "PORT=" .env 2^>nul') do set "PORT=%%p"
if not defined PORT set "PORT=8010"

echo Starting B2B Outbound OS on http://localhost:%PORT%
echo Close this window to stop the system.
start "" "http://localhost:%PORT%"
python main.py
pause
