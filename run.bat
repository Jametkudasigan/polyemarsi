@echo off
REM Polymarket BTC Bot - Quick Start (Windows)

echo Starting Polymarket BTC 5-Minute Bot...

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat

python -c "import py_clob_client" 2>nul
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt
)

python -m src.bot %*
pause
