@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -m venv .venv
    ) else (
        python -m venv .venv
    )
    if errorlevel 1 (
        echo Could not create a virtual environment. Install Python 3.11 or newer with Tcl/Tk support.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" -c "import tkinter, reportlab" >nul 2>nul
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Installation failed. Check the network connection and Python installation.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" app.py
if errorlevel 1 pause
endlocal