@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    py -m venv .venv
    if errorlevel 1 (
        echo Could not create virtual environment. Ensure Python is installed.
        pause
        exit /b 1
    )
)
call ".venv\Scripts\activate.bat"
echo Installing or checking required packages...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Package installation failed. Check your internet connection and Python installation.
    pause
    exit /b 1
)
echo Starting FinShield AI API at http://127.0.0.1:8001
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001 --reload
pause
