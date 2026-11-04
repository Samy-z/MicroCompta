@echo off
REM Launch MicroCompta on Windows.
REM First run also builds the virtual environment and makes the shortcuts.
REM "run.bat --setup" builds the environment and stops, without opening the app.
setlocal
cd /d "%~dp0"

REM The marker is written last, so an interrupted install is finished next time
REM instead of launching an app with half its dependencies.
if exist ".venv\.deps-ok" goto :ready

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    where py >nul 2>nul && py -3 -m venv .venv
    if not exist ".venv\Scripts\python.exe" python -m venv .venv
    if not exist ".venv\Scripts\python.exe" goto :err
)
echo Installing dependencies, this takes a minute...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :err
echo ok> ".venv\.deps-ok"

:ready
if "%~1"=="--setup" goto :eof

REM Shortcuts embed absolute paths, so they are made here rather than shipped.
if not exist "MicroCompta.lnk" (
    echo Creating shortcuts...
    ".venv\Scripts\python.exe" scripts\make_shortcut.py
)

start "" ".venv\Scripts\pythonw.exe" -m microcompta
goto :eof

:err
echo.
echo Setup failed: see the message above. Run this again to retry.
echo  - Python 3.11+ must be installed and on PATH.
echo  - If it mentions long paths, move this folder somewhere with a shorter path.
pause
exit /b 1
