@echo off
chcp 65001 >nul
rem Collects what the Pult knows about today's masters into a txt on the Desktop.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0check-shift.ps1"
pause
