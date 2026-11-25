@echo off
chcp 65001 >nul
rem Diagnostics collector for the Director app.
rem Comments in this file are kept plain ASCII on purpose: Cyrillic right
rem after "chcp 65001" has been seen to get garbled by cmd.exe on some
rem Windows builds (it reads the file in blocks before chcp takes effect).
rem All actual explanations live in PROCHTI MENYA.txt and the .ps1 file.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-diagnostics.ps1"
pause
