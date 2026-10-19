@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creating the DMM Photo Desk environment...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo Install Python 3.12 or newer from python.org, then run this file again.
        pause
        exit /b 1
    )
)
if not exist ".venv\dmm-installed-v1" (
    echo Installing dependencies. Internet access is needed for this first run.
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Installation failed. Check the message above and try again.
        pause
        exit /b 1
    )
    type nul > ".venv\dmm-installed-v1"
)
".venv\Scripts\python.exe" -m dmm %*
if errorlevel 1 pause
