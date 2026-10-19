@echo off
cd /d "%~dp0.."
if not exist .venv\Scripts\python.exe call install.bat
.venv\Scripts\python agent\print_agent.py
pause
