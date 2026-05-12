@echo off
REM ----------------------------------------------------------------------------
REM  OpenJarvis launcher (Windows)
REM  Spawns the backend (jarvis serve, FastAPI on :8000) and the frontend
REM  (Vite dev server on :5173) in two separate console windows that each
REM  run a WSL command.
REM
REM  On Win11, plain `start cmd ...` is consolidated into tabs in your
REM  existing Windows Terminal window, which makes the spawns easy to miss.
REM  We wrap with conhost.exe to force classic standalone console windows
REM  that always pop up as separate, clearly-visible windows.
REM
REM  Vite proxies /v1 and /health to localhost:8000, so both must be running.
REM ----------------------------------------------------------------------------

setlocal

set "PROJECT=%~dp0"
if "%PROJECT:~-1%"=="\" set "PROJECT=%PROJECT:~0,-1%"

REM The venv lives on the WSL filesystem (the Windows /mnt mount blocks
REM symlinks, so uv can't create a venv directly under the project).
set "VENV=$HOME/.venvs/openjarvis"

REM cmd.exe /k below keeps the spawned window open at a cmd prompt after
REM wsl/bash exits, so any error output from the inner command stays visible.
set "BACKEND_BASH=UV_PROJECT_ENVIRONMENT=%VENV% uv run jarvis serve"
echo.
echo  Starting OpenJarvis backend  (http://localhost:8000)
start "OpenJarvis Backend"  conhost.exe cmd.exe /k wsl.exe --cd "%PROJECT%"          -e bash -lc "%BACKEND_BASH%"

REM Frontend runs Windows-native npm (NOT under WSL). The /mnt mount blocks
REM symlink creation, so `npm install` fails inside WSL with EPERM; Windows
REM npm uses NTFS junctions for node_modules/.bin and works cleanly.
REM Auto-installs deps if the vite shim is missing (first run or partial install).
echo  Starting OpenJarvis frontend (http://localhost:5173)
start "OpenJarvis Frontend" /D "%PROJECT%\frontend" conhost.exe cmd.exe /k "if not exist node_modules\.bin\vite.cmd npm install && npm run dev"

echo.
echo  Waiting up to 30s for backend on http://localhost:8000/health ...
set /a tries=0
:probe
set /a tries+=1
curl.exe -s -f -m 1 http://localhost:8000/health >nul 2>&1
if not errorlevel 1 goto up
if %tries% geq 30 goto down
>nul timeout /t 1 /nobreak
goto probe

:up
echo  Backend is up.
goto report

:down
echo  Backend did not respond -- check the "OpenJarvis Backend" window for errors.
goto report

:report
echo.
echo  Backend:  http://localhost:8000
echo  Frontend: http://localhost:5173
echo.
echo  Close the spawned windows (or Ctrl+C inside) to stop.
echo.

endlocal
