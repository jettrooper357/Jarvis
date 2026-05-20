@echo off
setlocal

REM Stop OpenJarvis and reclaim WSL/Ollama memory.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-openjarvis.ps1"

endlocal
