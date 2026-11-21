@echo off
setlocal
title CenTRap
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
if errorlevel 1 (
    echo.
    echo CenTRap could not start. See the error above.
    pause
    exit /b 1
)
