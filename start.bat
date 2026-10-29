@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PORT=%CINEBOX_PORT%"
if "%PORT%"=="" set "PORT=8426"
title CINEBOX - %PORT%

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
  where py >nul 2>nul && set "PY=py -3"
)
if not defined PY goto nopython

%PY% -c "import sys;sys.exit(0)" >nul 2>nul
if errorlevel 1 goto nopython

set "CINEBOX_OPEN=1"
echo.
echo   PrivateCinema is starting on  http://127.0.0.1:%PORT%
echo   Keep this window open.  Press Ctrl+C (or close it) to stop.
echo.
%PY% app.py
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="2" (
  echo   [CINEBOX] Another instance is already running - window kept open.
  echo   Close this window when you are done.
  pause
)
exit /b %RC%

:nopython
echo.
echo   [CINEBOX] Python 3.10+ was not found.
echo   1) Install Python and tick "Add python.exe to PATH"
echo   2) Or run in this folder:  py -3 app.py
echo.
pause
exit /b 1
