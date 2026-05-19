@echo off
REM ----------------------------------------------------------------------------
REM  OpenJarvis launcher (Windows)
REM
REM  Bootstraps a fresh clone end-to-end:
REM    1. Verifies WSL + a Linux distro
REM    2. Verifies Node + npm on Windows
REM    3. Installs uv inside WSL if missing
REM    4. Installs espeak-ng inside WSL if missing (kokoro TTS dep)
REM    5. Runs `uv sync` with the speech extras
REM    6. Spawns the backend (jarvis serve, FastAPI on :8000) in WSL
REM    7. Spawns the frontend (Vite dev server on :5173) on Windows
REM    8. Waits for /health, prints status, and warns if Ollama is offline
REM
REM  Pre-reqs that the script CANNOT auto-install:
REM    - WSL2 + Ubuntu (`wsl --install -d Ubuntu` from an admin shell)
REM    - Node.js 18+ on Windows (https://nodejs.org)
REM    - Ollama (only needed if engine=ollama; https://ollama.com)
REM
REM  Spawned windows use conhost.exe so they pop up as separate, clearly-visible
REM  consoles on Win11 instead of being folded into Windows Terminal tabs.
REM ----------------------------------------------------------------------------

setlocal

set "PROJECT=%~dp0"
if "%PROJECT:~-1%"=="\" set "PROJECT=%PROJECT:~0,-1%"

REM venv lives on the WSL filesystem; the Windows /mnt mount blocks symlinks
REM so uv can't create a venv directly under the project tree.
set "VENV=$HOME/.venvs/openjarvis"

REM --- 1. WSL + distro --------------------------------------------------------
where wsl.exe >nul 2>&1
if errorlevel 1 (
    echo  ERROR: wsl.exe not found on PATH.
    echo  Install WSL2 + Ubuntu from an admin terminal:  wsl --install -d Ubuntu
    pause
    exit /b 1
)
wsl.exe -e true >nul 2>&1
if errorlevel 1 (
    echo  ERROR: WSL is installed but no default Linux distro is available.
    echo  Run:  wsl --install -d Ubuntu
    echo  Then sign in once so the distro is fully provisioned, and re-run start.bat.
    pause
    exit /b 1
)

REM --- 2. Node + npm on Windows ----------------------------------------------
where npm >nul 2>&1
if errorlevel 1 (
    echo  ERROR: npm not found on PATH. Install Node.js 18+ from https://nodejs.org
    echo  Then re-run start.bat.
    pause
    exit /b 1
)

REM --- 3. uv inside WSL (curl-installer; needs PATH refresh on first install)--
wsl.exe --cd "%PROJECT%" -e bash -lc "command -v uv >/dev/null" >nul 2>&1
if errorlevel 1 (
    echo  Installing uv in WSL ^(one-time^)...
    wsl.exe -e bash -lc "curl -LsSf https://astral.sh/uv/install.sh | sh"
    if errorlevel 1 (
        echo  ERROR: uv install failed. See output above.
        pause
        exit /b 1
    )
)

REM --- 4. espeak-ng (kokoro TTS phonemizer) -----------------------------------
REM  Without it, /v1/speech/synthesize returns 500. Install via `wsl -u root`
REM  so we never need a WSL user password (many Windows users never set one).
wsl.exe --cd "%PROJECT%" -e bash -c "command -v espeak-ng >/dev/null" >nul 2>&1
if errorlevel 1 (
    echo  Installing espeak-ng for Kokoro TTS in WSL ^(one-time^)...
    wsl.exe -u root -e bash -c "apt-get update -qq && apt-get install -y espeak-ng"
)

REM --- 5. Python venv sync (first run pulls ~1-2 GB of kokoro/torch wheels) --
echo.
echo  Syncing Python venv with speech extras ^(first run can take several minutes^)...
wsl.exe --cd "%PROJECT%" -e bash -lc "UV_PROJECT_ENVIRONMENT=%VENV% uv sync --extra server --extra speech --extra speech-tts-kokoro"
if errorlevel 1 (
    echo  ERROR: uv sync failed. See output above.
    pause
    exit /b 1
)

REM --- 6. Backend -------------------------------------------------------------
REM  cmd.exe /k keeps the spawned window open at a cmd prompt after wsl/bash
REM  exits, so any error output from the inner command stays visible.
REM  The speech extras pin huggingface_hub<1.0 / transformers<5 (see
REM  pyproject.toml conflicts) -- needed for kokoro to import cleanly.
REM  Default model for the OpenJarvis backend. qwen2.5-coder:7b: reliable
REM  tool-calling + code, fits the CPU/RAM budget. Change here to switch.
set "BACKEND_BASH=UV_PROJECT_ENVIRONMENT=%VENV% uv run --extra server --extra speech --extra speech-tts-kokoro jarvis serve --model qwen2.5-coder:7b"
echo.
echo  Starting OpenJarvis backend  (http://localhost:8000)
start "OpenJarvis Backend"  conhost.exe cmd.exe /k wsl.exe --cd "%PROJECT%" -e bash -lc "%BACKEND_BASH%"

REM --- 7. Frontend ------------------------------------------------------------
REM  Frontend runs Windows-native npm (NOT under WSL). The /mnt mount blocks
REM  symlink creation, so `npm install` fails inside WSL with EPERM; Windows
REM  npm uses NTFS junctions for node_modules/.bin and works cleanly.
REM  scripts\_start-frontend.bat auto-runs `npm install` on first launch.
echo  Starting OpenJarvis frontend (http://localhost:5173)
start "OpenJarvis Frontend" /D "%PROJECT%\frontend" conhost.exe cmd.exe /k call "%PROJECT%\scripts\_start-frontend.bat"

REM --- 8. Probe + report ------------------------------------------------------
echo.
echo  Waiting up to 60s for backend on http://localhost:8000/health ...
set /a tries=0
:probe
set /a tries+=1
curl.exe -s -f -m 1 http://localhost:8000/health >nul 2>&1
if not errorlevel 1 goto up
if %tries% geq 60 goto down
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
REM Best-effort Ollama check -- not fatal, just informative.
curl.exe -s -f -m 1 http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo.
    echo  WARNING: Ollama not detected at http://localhost:11434
    echo           Backend default engine is ollama; chat will fail until Ollama
    echo           is running. Install from https://ollama.com or change the
    echo           engine in ~/.openjarvis/config.toml.
)
echo.
echo  Close the spawned windows (or Ctrl+C inside) to stop.
echo.

endlocal
