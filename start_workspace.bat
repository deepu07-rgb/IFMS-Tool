@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
  if errorlevel 1 goto failure
  .venv\Scripts\python.exe -m pip install -r requirements.lock
  if errorlevel 1 goto failure
)
.venv\Scripts\python.exe launch.py
if errorlevel 1 goto failure
exit /b 0
:failure
echo Setup or startup failed. See the error above.
pause
exit /b 1
