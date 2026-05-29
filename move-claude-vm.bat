@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM  Moves the Claude Desktop VM bundle off C: to F: and leaves a
REM  directory junction behind so the app still finds everything at
REM  the original path. (batch port of move-claude-vm.ps1)
REM
REM  Run from an elevated Command Prompt AFTER fully quitting
REM  the Claude Desktop app.
REM ============================================================

set "SOURCE=C:\Users\james.e.thomas\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\vm_bundles\claudevm.bundle"
set "TARGET=F:\ClaudeVM\claudevm.bundle"

echo Source : %SOURCE%
echo Target : %TARGET%
echo.

REM 1. Make sure the Claude app / VM is not running (file would be locked).
set "RUNNING=0"
for %%P in (claude.exe vmmem.exe) do (
    tasklist /FI "IMAGENAME eq %%P" 2>nul | findstr /I "%%P" >nul
    if !errorlevel! equ 0 (
        set "RUNNING=1"
        echo     RUNNING: %%P
    )
)
if "!RUNNING!"=="1" (
    echo These processes are still running - quit Claude Desktop first.
    echo Aborting: close the Claude Desktop app and re-run.
    exit /b 1
)

REM 2. Sanity checks.
if not exist "%SOURCE%" (
    echo Source not found: %SOURCE%
    exit /b 1
)
fsutil reparsepoint query "%SOURCE%" >nul 2>&1
if !errorlevel! equ 0 (
    echo Source is already a link/junction -^> already moved?
    exit /b 1
)
if exist "%TARGET%" (
    echo Target already exists: %TARGET%  ^(remove it or pick another path^)
    exit /b 1
)

REM 3. Move with robocopy (resumable, good for large VHDX files).
for %%D in ("%TARGET%\..") do set "TARGETPARENT=%%~fD"
if not exist "%TARGETPARENT%" mkdir "%TARGETPARENT%"
echo Copying ~14 GB to F: (this can take a few minutes)...
robocopy "%SOURCE%" "%TARGET%" /E /MOVE /COPY:DAT /R:1 /W:1 /NFL /NDL /NP
REM robocopy success codes are 0-7; 8+ means real failure.
if !errorlevel! geq 8 (
    echo robocopy failed with code !errorlevel!
    exit /b 1
)

REM 4. Remove the now-empty source folder and create the junction.
if exist "%SOURCE%" rmdir /s /q "%SOURCE%"
mklink /J "%SOURCE%" "%TARGET%"
if !errorlevel! neq 0 (
    echo mklink failed with code !errorlevel!
    exit /b 1
)

REM 5. Verify.
echo.
echo Done.
echo Junction created: %SOURCE%  -^>  %TARGET%
echo Files now live on F:; relaunch Claude Desktop to confirm the VM still boots.
exit /b 0