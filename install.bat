@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
if not exist .env copy .env.example .env
echo.
echo Готово. Откройте файл .env, впишите BOT_TOKEN и ADMIN_IDS, затем запустите run.bat
pause
