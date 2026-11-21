@echo off
setlocal
set "CENTERAI_DATA=%~dp0.qa\alternative-data"
set "PUBLIC_URL=http://127.0.0.1:8003"
call "%~dp0Start-CenterAI.cmd" -Port 8003
