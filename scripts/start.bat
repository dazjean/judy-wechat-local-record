@echo off
setlocal
cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r backend\requirements.txt
set PYTHONPATH=%CD%\backend
pythonw -m app.boot
if errorlevel 1 python -m app.boot
endlocal
