@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================
echo  AI-assistant for incoming requests (GigaChat API)
echo ==============================================================

if not exist ".venv" (
  echo Creating virtual environment (.venv)...
  python -m venv .venv
  if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ from python.org
    pause
    exit /b 1
  )
)

call .venv\Scripts\activate.bat

echo Installing libraries (first run only, takes ~1 minute)...
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
  echo ERROR: cannot install libraries. Check your internet connection.
  pause
  exit /b 1
)

echo Starting application...
python app.py
pause