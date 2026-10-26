@echo off
cd /d "%~dp0"
echo FINSHIELD AI ADVANCED UPGRADE - serving frontend:
echo %~dp0frontend
py -m http.server 5500 --bind 127.0.0.1 --directory "%~dp0frontend"
pause
