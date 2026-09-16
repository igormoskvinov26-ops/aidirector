@echo off
chcp 65001 >nul
rem Остановить Директора. Данные остаются на месте — при следующем запуске
rem всё будет как было.
cd /d "%~dp0"
docker compose --env-file "%~dp0..\.env" down
echo.
echo Директор остановлен. Данные сохранены.
pause
