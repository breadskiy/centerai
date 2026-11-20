@echo off
setlocal
cd /d "%~dp0"
set "PYEXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"
"%PYEXE%" "server.py"
if errorlevel 1 echo Check Ollama, the running server and the instructions in README.txt.
pause
