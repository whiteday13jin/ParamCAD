@echo off
cd /d "%~dp0"

set "PY_CMD="
where python >nul 2>nul
if not errorlevel 1 set "PY_CMD=python"

if "%PY_CMD%"=="" (
  where py >nul 2>nul
  if not errorlevel 1 set "PY_CMD=py -3"
)

if "%PY_CMD%"=="" (
  echo [ERROR] Python not found. Please install Python 3.11+ and add to PATH.
  pause
  exit /b 1
)

%PY_CMD% -c "import fastapi,uvicorn,jinja2,openpyxl,pydantic" >nul 2>nul
if errorlevel 1 (
  %PY_CMD% -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
  )
)

netstat -ano | findstr ":8000" >nul
if errorlevel 1 (
  start "ParamCAD Server" /min %PY_CMD% -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --reload
  timeout /t 2 >nul
)

start "" "http://127.0.0.1:8000"
exit /b 0
