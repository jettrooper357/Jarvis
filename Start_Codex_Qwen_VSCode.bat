@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ============================================================
REM Object:         Start_Codex_AI.bat
REM Author:         Jim Thomas
REM Revision:       1.2
REM Revision Date:  05/18/2026
REM Created:        05/18/2026
REM
REM History:
REM When          Who           Rev   Description
REM ------------- ------------- ----- --------------------------------------
REM 05/18/2026    Jim Thomas    1.0   Initial version. Launches OpenAI Codex in either
REM                                   online web-login mode or local Ollama mode.
REM                                   Includes WSL/Ollama checks, model validation,
REM                                   endpoint checks, and step/error logging.
REM 05/18/2026    Jim Thomas    1.1   Fixed online mode. Online is now the default mode.
REM                                   Online mode removes active local Codex config so Codex
REM                                   cannot accidentally launch qwen2.5-coder through Ollama.
REM                                   Local Ollama mode only runs when explicitly requested.
REM 05/18/2026    Jim Thomas    1.2   Forced Codex to always start with
REM                                   --dangerously-bypass-approvals-and-sandbox in both
REM                                   online and local modes by centralizing the required
REM                                   launch parameter in CODEX_REQUIRED_ARGS.
REM ============================================================

TITLE Start Codex AI

REM ============================================================
REM USER SETTINGS
REM ============================================================

SET "PROJECT_FOLDER=F:\Web Projects\Jarvis"

REM Local Ollama settings.
SET "OLLAMA_WINDOWS_MODEL_FOLDER=F:\Ollama\Models"
SET "OLLAMA_WSL_MODEL_FOLDER=/mnt/f/Ollama/Models"
SET "OLLAMA_HOST_URL=http://localhost:11434"
SET "OLLAMA_WSL_HOST=0.0.0.0:11434"

REM Keep local small for this hardware.
SET "LOCAL_CODEX_MODEL=qwen2.5-coder:7b"

REM Codex config.
SET "CODEX_CONFIG_FOLDER=%USERPROFILE%\.codex"
SET "CODEX_CONFIG_FILE=%USERPROFILE%\.codex\config.toml"
SET "CODEX_LOCAL_CONFIG_BACKUP=%USERPROFILE%\.codex\config.local_ollama_backup.toml"

REM Log settings.
SET "LOG_FOLDER=%PROJECT_FOLDER%\Logs"
SET "LOG_FILE=%LOG_FOLDER%\Start_Codex_AI.log"

REM Optional behavior.
SET "OPEN_VSCODE=1"
SET "STOP_WINDOWS_OLLAMA=1"
SET "RESET_WSL_FIRST=0"

REM ============================================================
REM CODEX LAUNCH ARGUMENTS
REM
REM CHANGE 1.2:
REM   This is now centralized so every launch path uses the same
REM   required safety-bypass/yolo argument.
REM ============================================================

SET "CODEX_REQUIRED_ARGS=--dangerously-bypass-approvals-and-sandbox"

REM Online mode:
REM   Uses OpenAI / ChatGPT login.
REM   Does NOT specify a local model.
SET "CODEX_ONLINE_ARGS=%CODEX_REQUIRED_ARGS%"

REM Local mode:
REM   Uses Ollama OSS mode and the local model.
SET "CODEX_LOCAL_ARGS=--oss -m ""%LOCAL_CODEX_MODEL%"" %CODEX_REQUIRED_ARGS%"

REM ============================================================
REM INITIALIZE LOGGING
REM ============================================================

if not exist "%LOG_FOLDER%" mkdir "%LOG_FOLDER%" >nul 2>&1

call :Log INFO "============================================================"
call :Log INFO "Starting Start_Codex_AI.bat"
call :Log INFO "Project folder: %PROJECT_FOLDER%"
call :Log INFO "Log file: %LOG_FILE%"

REM ============================================================
REM DETERMINE MODE
REM
REM Online is the default.
REM
REM Usage:
REM   Start_Codex_AI.bat
REM   Start_Codex_AI.bat online
REM   Start_Codex_AI.bat local
REM ============================================================

SET "RUN_MODE=%~1"

if "%RUN_MODE%"=="" (
    SET "RUN_MODE=online"
)

if /I "%RUN_MODE%"=="web" SET "RUN_MODE=online"
if /I "%RUN_MODE%"=="cloud" SET "RUN_MODE=online"
if /I "%RUN_MODE%"=="chatgpt" SET "RUN_MODE=online"
if /I "%RUN_MODE%"=="ollama" SET "RUN_MODE=local"

if /I not "%RUN_MODE%"=="online" if /I not "%RUN_MODE%"=="local" (
    call :Log ERROR "Invalid mode: %RUN_MODE%"
    echo.
    echo ERROR: Invalid mode.
    echo Use:
    echo   Start_Codex_AI.bat
    echo   Start_Codex_AI.bat online
    echo   Start_Codex_AI.bat local
    echo.
    pause
    exit /b 1
)

call :Log INFO "Selected mode: %RUN_MODE%"
call :Log INFO "Required Codex args: %CODEX_REQUIRED_ARGS%"

REM ============================================================
REM COMMON CHECKS
REM ============================================================

call :CheckProjectFolder
if errorlevel 1 goto FAIL

call :CheckCommand "codex"
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

if /I "%RUN_MODE%"=="online" goto CODEX_ONLINE
if /I "%RUN_MODE%"=="local" goto CODEX_LOCAL

goto FAIL

REM ============================================================
REM CODEX ONLINE MODE
REM ============================================================

:CODEX_ONLINE
call :Log INFO "Preparing Codex ONLINE mode."

REM ------------------------------------------------------------
REM Online mode must not inherit local Ollama config.
REM If config.toml contains local provider/model settings, Codex
REM may launch qwen2.5-coder instead of online ChatGPT/OpenAI.
REM ------------------------------------------------------------

call :DisableLocalCodexConfig
if errorlevel 1 goto FAIL

REM Clear local/proxy variables in this CMD session.
SET "OPENAI_BASE_URL="
SET "OPENAI_API_BASE="
SET "OLLAMA_HOST="
SET "ANTHROPIC_BASE_URL="
SET "ANTHROPIC_API_KEY="
SET "ANTHROPIC_AUTH_TOKEN="

call :OpenVSCode

call :Log INFO "Launching Codex ONLINE mode."
call :Log INFO "Command: codex %CODEX_ONLINE_ARGS%"

echo.
echo ============================================================
echo Launching Codex ONLINE mode
echo ============================================================
echo.
echo This should use your OpenAI/ChatGPT Codex login.
echo It should NOT show qwen2.5-coder.
echo.
echo Forced Codex parameter:
echo   %CODEX_REQUIRED_ARGS%
echo.

start "Codex - Online" cmd /k "cd /d ""%PROJECT_FOLDER%"" && codex %CODEX_ONLINE_ARGS%"

call :Log INFO "Codex online window launched with required args."
goto SUCCESS

REM ============================================================
REM CODEX LOCAL MODE
REM ============================================================

:CODEX_LOCAL
call :Log INFO "Preparing Codex LOCAL Ollama mode."

call :CheckCommand "wsl"
if errorlevel 1 goto FAIL

call :PrepareOllama
if errorlevel 1 goto FAIL

call :ValidateCodexLocalModel
if errorlevel 1 goto FAIL

call :OpenVSCode

call :Log INFO "Launching Codex LOCAL mode."
call :Log INFO "Command: codex %CODEX_LOCAL_ARGS%"

echo.
echo ============================================================
echo Launching Codex LOCAL Ollama mode
echo ============================================================
echo.
echo Model:
echo   %LOCAL_CODEX_MODEL%
echo.
echo Forced Codex parameter:
echo   %CODEX_REQUIRED_ARGS%
echo.

start "Codex - Local Ollama" cmd /k "cd /d ""%PROJECT_FOLDER%"" && codex %CODEX_LOCAL_ARGS%"

call :Log INFO "Codex local window launched with required args."
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

:DisableLocalCodexConfig
call :Log INFO "Checking for active Codex config."

if not exist "%CODEX_CONFIG_FOLDER%" (
    call :Log INFO "Creating Codex config folder: %CODEX_CONFIG_FOLDER%"
    mkdir "%CODEX_CONFIG_FOLDER%" >nul 2>&1
)

if exist "%CODEX_CONFIG_FILE%" (
    call :Log WARN "Active Codex config found. Backing it up and removing it for online mode."

    if exist "%CODEX_LOCAL_CONFIG_BACKUP%" (
        call :Log INFO "Removing old local config backup: %CODEX_LOCAL_CONFIG_BACKUP%"
        del /q "%CODEX_LOCAL_CONFIG_BACKUP%" >nul 2>&1
    )

    copy "%CODEX_CONFIG_FILE%" "%CODEX_LOCAL_CONFIG_BACKUP%" >nul 2>&1
    if errorlevel 1 (
        call :Log ERROR "Could not back up Codex config."
        echo ERROR: Could not back up Codex config:
        echo %CODEX_CONFIG_FILE%
        exit /b 1
    )

    del /q "%CODEX_CONFIG_FILE%" >nul 2>&1
    if errorlevel 1 (
        call :Log ERROR "Could not remove active Codex config."
        echo ERROR: Could not remove active Codex config:
        echo %CODEX_CONFIG_FILE%
        exit /b 1
    )

    call :Log INFO "Active Codex config removed for online mode."
) else (
    call :Log INFO "No active Codex config found. Online mode is clean."
)

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

:ValidateCodexLocalModel
call :Log INFO "Validating Codex local model: %LOCAL_CODEX_MODEL%"

call :Log INFO "Checking/pulling local model."
wsl bash -lc "ollama list | grep -qF '%LOCAL_CODEX_MODEL%' || ollama pull '%LOCAL_CODEX_MODEL%'" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :Log ERROR "Could not verify or pull model: %LOCAL_CODEX_MODEL%"
    exit /b 1
)

call :Log INFO "Testing /v1/responses non-streaming endpoint."

SET "RESPONSES_JSON=%TEMP%\codex_local_responses_test.json"
(
echo {"model":"%LOCAL_CODEX_MODEL%","input":"Reply with ok only.","max_output_tokens":10,"stream":false}
) > "%RESPONSES_JSON%"

curl -sf --max-time 180 -o nul -X POST "%OLLAMA_HOST_URL%/v1/responses" -H "Content-Type: application/json" -d @"%RESPONSES_JSON%" >> "%LOG_FILE%" 2>&1
SET "RESPONSES_RC=%ERRORLEVEL%"
del /q "%RESPONSES_JSON%" >nul 2>&1

if not "%RESPONSES_RC%"=="0" (
    call :Log ERROR "Codex local model failed /v1/responses. curl exit code: %RESPONSES_RC%"
    echo ERROR: Codex local model failed /v1/responses.
    echo Model: %LOCAL_CODEX_MODEL%
    echo Check log:
    echo %LOG_FILE%
    exit /b 1
)

call :Log INFO "Codex local model passed /v1/responses."
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

:SUCCESS
call :Log INFO "Start_Codex_AI.bat completed successfully."
echo.
echo Codex launcher completed.
echo Mode:
echo   %RUN_MODE%
echo Required Codex args:
echo   %CODEX_REQUIRED_ARGS%
echo Log:
echo   %LOG_FILE%
echo.
pause
exit /b 0

:FAIL
call :Log ERROR "Start_Codex_AI.bat failed."
echo.
echo ERROR: Codex launcher failed.
echo Log:
echo   %LOG_FILE%
echo.
pause
exit /b 1