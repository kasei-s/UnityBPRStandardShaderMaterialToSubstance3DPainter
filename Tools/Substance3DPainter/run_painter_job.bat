@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem === run_painter_job.bat (Fixed16.15.0) ===
rem Usage:
rem   run_painter_job.bat "C:\path\to\job.json"
rem If no argument is given, job.json next to this bat is used.

set "SCRIPT_DIR=%~dp0"
set "PY_FILE=%SCRIPT_DIR%run_painter_job.py"

if "%~1"=="" (
  set "JOB_JSON=%SCRIPT_DIR%job.json"
) else (
  set "JOB_JSON=%~1"
)

echo === run_painter_job.bat (Fixed16.15.0) ===
echo PY_FILE="%PY_FILE%"
echo JOB_JSON="%JOB_JSON%"
echo.

if not exist "%PY_FILE%" (
  echo [ERROR] run_painter_job.py not found next to this bat:
  echo   "%PY_FILE%"
  pause
  exit /b 2
)

if not exist "%JOB_JSON%" (
  echo [ERROR] job.json not found:
  echo   "%JOB_JSON%"
  pause
  exit /b 3
)

where python >nul 2>nul
if %errorlevel%==0 (
  set "PY=python"
) else (
  set "PY=py -3"
)

echo [python] Running "%PY_FILE%" ...
%PY% "%PY_FILE%" "%JOB_JSON%"
set "RC=%errorlevel%"

echo.
echo [DONE] exit code = %RC%

if not "%RC%"=="0" (
  echo Job runner failed.
  pause
  exit /b %RC%
)

pause
exit /b 0
