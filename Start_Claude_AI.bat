@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ============================================================
REM Object:         Start_Claude_AI.bat
REM Author:         Jim Thomas
REM Revision:       1.0
REM Revision Date:  05/18/2026
REM Created:        05/18/2026
REM
REM History:
REM When          Who           Rev   Description
REM ------------- ------------- ----- --------------------------------------
REM 05/18/2026    Jim Thomas    1.0   Initial version. Launches Claude Code in either
REM                                   online web-login mode or local Ollama mode.
REM                                   Includes WSL/Ollama checks, model validation,
REM                                   Anthropic-compatible endpoint checks, and
REM                                   step/error logging.
REM ============================================================

TITLE Start Claude AI

REM ============================================================
REM USER SETTINGS
REM ============================================================

SET "PROJECT_FOLDER=F:\Web Projects\Jarvis"

REM Local Ollama settings.
SET "OLLAMA_WINDOWS_MODEL_FOLDER=F:\Ollama\Models"
SET "OLLAMA_WSL_MODEL_FOLDER=/mnt/f/Ollama/Models"
SET "OLLAMA_HOST_URL=http://localhost:11434"
SET "OLLAMA_WSL_HOST=0.0.0.0:11434"

REM Keep this small for your hardware.
REM Ollama's Claude Code documentation recommends models like qwen3.5,
REM but this value is intentionally editable.
SET "LOCAL_CLAUDE_MODEL=qwen2.5-coder:7b"

REM If you later pull a better small Claude-Code-compatible model,
REM change LOCAL_CLAUDE_MODEL above. Do not rewrite the whole script.
REM That would be work, and we are pretending to avoid that now.

REM Log settings.
SET "LOG_FOLDER=%PROJECT_FOLDER%\Logs"
SET "LOG_FILE=%LOG_FOLDER%\Start_Claude_AI.log"

REM Optional behavior.
SET "OPEN_VSCODE=1"
SET "STOP_WINDOWS_OLLAMA=1"
SET "RESET_WSL_FIRST=0"

REM Claude launch settings.
SET "CLAUDE_ONLINE_ARGS="
SET "CLAUDE_LOCAL_ARGS=--model ""%LOCAL_CLAUDE_MODEL%"""

REM OpenJarvis web stack settings.
REM The backend MUST be running or the Vite dev server gets ECONNREFUSED
REM on every /v1 and /health proxy call. Edit the values; do not rewrite
REM the script.
SET "START_OPENJARVIS_STACK=1"
REM Default model for the OpenJarvis backend (reliable tool-calling + code).
SET "OJ_BACKEND_CMD=uv run jarvis serve --model qwen2.5-coder:7b"
SET "OJ_BACKEND_HEALTH_URL=http://localhost:8000/health"
SET "OJ_FRONTEND_FOLDER=%PROJECT_FOLDER%\frontend"
SET "OJ_FRONTEND_CMD=npm run dev"
SET "OJ_FRONTEND_URL=http://localhost:5173"
SET "OJ_OPEN_BROWSER=1"

REM ============================================================
REM INITIALIZE LOGGING
REM ============================================================

if not exist "%LOG_FOLDER%" mkdir "%LOG_FOLDER%" >nul 2>&1

call :Log INFO "============================================================"
call :Log INFO "Starting Start_Claude_AI.bat"
call :Log INFO "Project folder: %PROJECT_FOLDER%"
call :Log INFO "Log file: %LOG_FILE%"

REM ============================================================
REM DETERMINE MODE
REM ============================================================

SET "RUN_MODE=%~1"

if "%RUN_MODE%"=="" (
    echo.
    echo Select Claude mode:
    echo   1. Online / web login
    echo   2. Local / Ollama model
    echo.
    choice /C 12 /N /M "Enter choice [1-2]: "
    if errorlevel 2 SET "RUN_MODE=local"
    if errorlevel 1 if not "%RUN_MODE%"=="local" SET "RUN_MODE=online"
)

if /I "%RUN_MODE%"=="web" SET "RUN_MODE=online"
if /I "%RUN_MODE%"=="cloud" SET "RUN_MODE=online"
if /I "%RUN_MODE%"=="ollama" SET "RUN_MODE=local"

if /I not "%RUN_MODE%"=="online" if /I not "%RUN_MODE%"=="local" (
    call :Log ERROR "Invalid mode: %RUN_MODE%"
    echo.
    echo ERROR: Invalid mode.
    echo Use:
    echo   Start_Claude_AI.bat online
    echo   Start_Claude_AI.bat local
    echo.
    pause
    exit /b 1
)

call :Log INFO "Selected mode: %RUN_MODE%"

REM ============================================================
REM COMMON CHECKS
REM ============================================================

call :CheckProjectFolder
if errorlevel 1 goto FAIL

call :CheckCommand "claude"
if errorlevel 1 goto FAIL

call :CheckCommand "curl"
if errorlevel 1 goto FAIL

if "%OPEN_VSCODE%"=="1" (
    call :CheckCommand "code"
    if errorlevel 1 (
        call :Log WARN "VS Code command 'code' was not found. Continuing without opening VS Code."
    )
)

REM ============================================================
REM ROUTE BY MODE
REM ============================================================

if /I "%RUN_MODE%"=="online" goto CLAUDE_ONLINE
if /I "%RUN_MODE%"=="local" goto CLAUDE_LOCAL

goto FAIL

REM ============================================================
REM CLAUDE ONLINE MODE
REM ============================================================

:CLAUDE_ONLINE
call :Log INFO "Preparing Claude online/web-login mode."

REM Clear local/proxy variables in this cmd session so Claude uses normal web-login/subscription behavior.
SET "ANTHROPIC_BASE_URL="
SET "ANTHROPIC_API_KEY="
SET "ANTHROPIC_AUTH_TOKEN="
SET "ANTHROPIC_CUSTOM_HEADERS="
SET "ANTHROPIC_CUSTOM_MODEL_OPTION="
SET "ANTHROPIC_DEFAULT_OPUS_MODEL="
SET "ANTHROPIC_DEFAULT_SONNET_MODEL="
SET "ANTHROPIC_DEFAULT_HAIKU_MODEL="

call :OpenVSCode

call :Log INFO "Launching Claude online mode."
call :Log INFO "Command: claude %CLAUDE_ONLINE_ARGS%"

start "Claude - Online" cmd /k "cd /d ""%PROJECT_FOLDER%"" && claude %CLAUDE_ONLINE_ARGS%"

call :Log INFO "Claude online window launched."
goto SUCCESS

REM ============================================================
REM CLAUDE LOCAL MODE
REM ============================================================

:CLAUDE_LOCAL
call :Log INFO "Preparing Claude local/Ollama mode."

call :CheckCommand "wsl"
if errorlevel 1 goto FAIL

call :PrepareOllama
if errorlevel 1 goto FAIL

call :ValidateClaudeLocalModel
if errorlevel 1 goto FAIL

call :OpenVSCode

call :Log INFO "Launching Claude local mode."
call :Log INFO "Command: claude %CLAUDE_LOCAL_ARGS%"
call :Log INFO "ANTHROPIC_BASE_URL=%OLLAMA_HOST_URL%"

REM These variables are required for Claude Code to use Ollama's Anthropic-compatible API.
REM They are set only inside the launched cmd window.
start "Claude - Local Ollama" cmd /k "cd /d ""%PROJECT_FOLDER%"" && set ANTHROPIC_AUTH_TOKEN=ollama&& set ANTHROPIC_API_KEY=&& set ANTHROPIC_BASE_URL=%OLLAMA_HOST_URL%&& claude %CLAUDE_LOCAL_ARGS%"

call :Log INFO "Claude local window launched."
goto SUCCESS

REM ============================================================
REM SUBROUTINES
REM ============================================================

:CheckProjectFolder
if not exist "%PROJECT_FOLDER%" (
    call :Log ERROR "Project folder does not exist: %PROJECT_FOLDER%"
    echo ERROR: Project folder does not exist:
    echo %PROJECT_FOLDER%
    exit /b 1
)

call :Log INFO "Project folder exists."
exit /b 0

:CheckCommand
SET "COMMAND_NAME=%~1"

where "%COMMAND_NAME%" >nul 2>&1
if errorlevel 1 (
    call :Log ERROR "Required command not found in PATH: %COMMAND_NAME%"
    echo ERROR: Required command not found in PATH: %COMMAND_NAME%
    exit /b 1
)

call :Log INFO "Command found: %COMMAND_NAME%"
exit /b 0

:OpenVSCode
if not "%OPEN_VSCODE%"=="1" (
    call :Log INFO "OPEN_VSCODE is disabled."
    exit /b 0
)

where code >nul 2>&1
if errorlevel 1 (
    call :Log WARN "VS Code command 'code' not found. Skipping VS Code launch."
    exit /b 0
)

call :Log INFO "Opening VS Code."
start "" code "%PROJECT_FOLDER%"
exit /b 0

:PrepareOllama
call :Log INFO "Preparing WSL Ollama service."

if "%RESET_WSL_FIRST%"=="1" (
    call :Log WARN "RESET_WSL_FIRST enabled. Running wsl --shutdown."
    wsl --shutdown >> "%LOG_FILE%" 2>&1
    ping -n 8 127.0.0.1 >nul
)

if "%STOP_WINDOWS_OLLAMA%"=="1" (
    call :Log INFO "Checking for Windows-side ollama.exe."

    tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe" >nul
    if not errorlevel 1 (
        call :Log WARN "Stopping Windows-side ollama.exe to prevent port conflicts."
        taskkill /F /IM ollama.exe >> "%LOG_FILE%" 2>&1
        ping -n 3 127.0.0.1 >nul
    ) else (
        call :Log INFO "Windows-side ollama.exe is not running."
    )
)

if not exist "%OLLAMA_WINDOWS_MODEL_FOLDER%" (
    call :Log INFO "Creating Windows Ollama model folder: %OLLAMA_WINDOWS_MODEL_FOLDER%"
    mkdir "%OLLAMA_WINDOWS_MODEL_FOLDER%" >> "%LOG_FILE%" 2>&1
)

call :Log INFO "Configuring WSL ollama.service."
wsl -u root bash -lc "mkdir -p '%OLLAMA_WSL_MODEL_FOLDER%' /etc/systemd/system/ollama.service.d; chmod -R a+rwX '%OLLAMA_WSL_MODEL_FOLDER%' 2>/dev/null; printf '[Service]\nEnvironment=OLLAMA_MODELS=%OLLAMA_WSL_MODEL_FOLDER%\nEnvironment=OLLAMA_HOST=%OLLAMA_WSL_HOST%\nEnvironment=OLLAMA_KEEP_ALIVE=30m\nEnvironment=OLLAMA_NUM_PARALLEL=1\n' > /etc/systemd/system/ollama.service.d/override.conf; systemctl daemon-reload; systemctl enable --now ollama; systemctl restart ollama" >> "%LOG_FILE%" 2>&1

if errorlevel 1 (
    call :Log WARN "WSL root service command returned an error. Continuing to validate service state."
)

ping -n 5 127.0.0.1 >nul

call :Log INFO "Checking WSL Ollama version."
wsl bash -lc "ollama --version 2>/dev/null || true" >> "%LOG_FILE%" 2>&1

call :Log INFO "Checking WSL ollama.service status."
wsl bash -lc "systemctl is-active --quiet ollama" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :Log ERROR "WSL ollama.service is not active."
    echo ERROR: WSL ollama.service is not active.
    echo Check log:
    echo %LOG_FILE%
    exit /b 1
)

call :WaitForUrl "%OLLAMA_HOST_URL%/api/tags" "Windows Ollama API"
if errorlevel 1 exit /b 1

call :Log INFO "Ollama is ready."
exit /b 0

:ValidateClaudeLocalModel
call :Log INFO "Validating Claude local model: %LOCAL_CLAUDE_MODEL%"

call :Log INFO "Checking/pulling local model."
wsl bash -lc "ollama list | grep -qF '%LOCAL_CLAUDE_MODEL%' || ollama pull '%LOCAL_CLAUDE_MODEL%'" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :Log ERROR "Could not verify or pull model: %LOCAL_CLAUDE_MODEL%"
    exit /b 1
)

call :Log INFO "Testing Anthropic-compatible /v1/messages endpoint."

SET "MESSAGES_JSON=%TEMP%\claude_local_messages_test.json"
(
echo {"model":"%LOCAL_CLAUDE_MODEL%","max_tokens":10,"stream":false,"messages":[{"role":"user","content":"Reply with ok only."}]}
) > "%MESSAGES_JSON%"

curl -sf --max-time 180 -o nul -X POST "%OLLAMA_HOST_URL%/v1/messages" -H "Content-Type: application/json" -H "x-api-key: ollama" -H "anthropic-version: 2023-06-01" -d @"%MESSAGES_JSON%" >> "%LOG_FILE%" 2>&1
SET "MESSAGES_RC=%ERRORLEVEL%"
del /q "%MESSAGES_JSON%" >nul 2>&1

if not "%MESSAGES_RC%"=="0" (
    call :Log ERROR "Claude local model failed /v1/messages. curl exit code: %MESSAGES_RC%"
    echo ERROR: Claude local model failed Anthropic-compatible /v1/messages.
    echo Model: %LOCAL_CLAUDE_MODEL%
    echo Check log:
    echo %LOG_FILE%
    exit /b 1
)

call :Log INFO "Claude local model passed /v1/messages."
exit /b 0

:WaitForUrl
SET "TEST_URL=%~1"
SET "TEST_NAME=%~2"
SET "MAX_TRIES=30"
SET "TRY_COUNT=0"

:WAIT_LOOP
curl -s "%TEST_URL%" >nul 2>&1
if not errorlevel 1 (
    call :Log INFO "%TEST_NAME% is responding: %TEST_URL%"
    exit /b 0
)

set /a TRY_COUNT+=1
if %TRY_COUNT% GEQ %MAX_TRIES% (
    call :Log ERROR "%TEST_NAME% did not respond after %MAX_TRIES% attempts: %TEST_URL%"
    echo ERROR: %TEST_NAME% did not respond.
    echo URL: %TEST_URL%
    exit /b 1
)

call :Log WARN "%TEST_NAME% not ready. Attempt %TRY_COUNT% of %MAX_TRIES%."
ping -n 3 127.0.0.1 >nul
goto WAIT_LOOP

:Log
SET "LOG_LEVEL=%~1"
SET "LOG_MESSAGE=%~2"
SET "TS=%DATE% %TIME%"
echo [%TS%] [%LOG_LEVEL%] %LOG_MESSAGE%
echo [%TS%] [%LOG_LEVEL%] %LOG_MESSAGE%>> "%LOG_FILE%"
exit /b 0

:StartOpenJarvisStack
if not "%START_OPENJARVIS_STACK%"=="1" (
    call :Log INFO "START_OPENJARVIS_STACK disabled. Skipping web stack launch."
    exit /b 0
)

where uv >nul 2>&1
if errorlevel 1 (
    call :Log ERROR "'uv' not found in PATH. Cannot start the OpenJarvis backend. Install uv or clear START_OPENJARVIS_STACK."
    exit /b 1
)

call :Log INFO "Launching OpenJarvis backend: %OJ_BACKEND_CMD%"
start "OpenJarvis - Backend" cmd /k "cd /d ""%PROJECT_FOLDER%"" && %OJ_BACKEND_CMD%"

call :WaitForUrl "%OJ_BACKEND_HEALTH_URL%" "OpenJarvis backend"
if errorlevel 1 (
    call :Log ERROR "OpenJarvis backend did not become healthy. Frontend would only get ECONNREFUSED, so the frontend launch is skipped."
    exit /b 1
)

if not exist "%OJ_FRONTEND_FOLDER%" (
    call :Log WARN "Frontend folder not found: %OJ_FRONTEND_FOLDER%. Skipping frontend launch."
    exit /b 0
)

where npm >nul 2>&1
if errorlevel 1 (
    call :Log WARN "'npm' not found in PATH. Skipping frontend launch. Backend is up at %OJ_BACKEND_HEALTH_URL%."
    exit /b 0
)

call :Log INFO "Launching OpenJarvis frontend: %OJ_FRONTEND_CMD%"
start "OpenJarvis - Frontend" cmd /k "cd /d ""%OJ_FRONTEND_FOLDER%"" && %OJ_FRONTEND_CMD%"

if "%OJ_OPEN_BROWSER%"=="1" (
    call :Log INFO "Opening browser: %OJ_FRONTEND_URL%"
    start "" "%OJ_FRONTEND_URL%"
)

exit /b 0

:SUCCESS
call :StartOpenJarvisStack
if errorlevel 1 (
    call :Log WARN "OpenJarvis web stack did not start cleanly. The Claude window is still up; see messages above and the log."
)
call :Log INFO "Start_Claude_AI.bat completed successfully."
echo.
echo Claude launcher completed.
echo Log:
echo %LOG_FILE%
echo.
pause
exit /b 0

:FAIL
call :Log ERROR "Start_Claude_AI.bat failed."
echo.
echo ERROR: Claude launcher failed.
echo Log:
echo %LOG_FILE%
echo.
pause
exit /b 1