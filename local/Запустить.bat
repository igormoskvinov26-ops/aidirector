@echo off
chcp 65001 >nul
rem Двойной щелчок по этому файлу запускает Директора на Windows.
cd /d "%~dp0"
bash start.sh
echo.
pause
