@echo off
chcp 65001 >nul
rem Сборка «Тюша Печать» в один файл agent\dist\TyushaPrint.exe (нужен Windows и install.bat в папке бота).
rem Готовый exe положите на сервер в ту же папку agent\dist — панель отдаёт его по кнопке «Скачать программу».
cd /d "%~dp0.."
set ROOT=%CD%
.venv\Scripts\python -m pip install -q "pyinstaller>=6.6"
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name TyushaPrint --icon "%ROOT%\agent\assets\icon.ico" ^
  --add-data "%ROOT%\agent\assets;assets" --paths "%ROOT%" ^
  --distpath "%ROOT%\agent\dist" --workpath "%ROOT%\agent\build" --specpath "%ROOT%\agent\build" ^
  "%ROOT%\agent\tyusha_print.py"
echo.
echo Готово: agent\dist\TyushaPrint.exe
pause
