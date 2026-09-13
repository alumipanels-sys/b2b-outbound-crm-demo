@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo   B2B Outbound OS - One-time Installer (Windows)
echo ============================================
echo.
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found.
  echo Install Python 3.10 from https://www.python.org/downloads/
  echo Tick "Add python.exe to PATH", then run this file again.
  pause
  exit /b 1
)
python -c "import sys; sys.exit(0 if sys.version_info.major == 3 and sys.version_info.minor == 10 else 1)"
if errorlevel 1 (
  python -c "import sys; print('You have Python ' + sys.version.split()[0])"
  echo.
  echo [ERROR] B2B Outbound OS requires Python 3.10.
  echo Download 3.10 from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during install.
  pause
  exit /b 1
)
if not exist ".env" copy ".env.example" ".env" >nul
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo Install finished. Start the system with start.bat
echo Then open http://localhost:8010 and create your owner account.
pause

