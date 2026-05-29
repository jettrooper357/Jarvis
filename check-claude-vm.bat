@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM  Claude_VM_PreFlight_Check (batch port of check-claude-vm.ps1)
REM  Author:  Jim Thomas
REM  Created: 05/29/2026
REM
REM  Usage:
REM    check-claude-vm.bat
REM    check-claude-vm.bat "C:\Path\To\claudevm.bundle"
REM
REM  Notes:
REM    - Read-only. Does not stop processes, move files, or delete anything.
REM ============================================================

set "SOURCE=%~1"
if "%SOURCE%"=="" set "SOURCE=C:\Users\james.e.thomas\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\vm_bundles\claudevm.bundle"

set "HASWARNING=0"

echo === Claude VM pre-flight check ===
echo.

REM ============================================================
REM 1. Check for running processes likely to lock Claude VM files
REM ============================================================
echo Step 1: Checking Claude / VM-related processes...

set "LOCKFOUND=0"
for %%P in (claude.exe vmmem.exe vmmemWSL.exe) do (
    tasklist /FI "IMAGENAME eq %%P" 2>nul | findstr /I "%%P" >nul
    if !errorlevel! equ 0 (
        set "LOCKFOUND=1"
        echo     RUNNING: %%P
    )
)

if "!LOCKFOUND!"=="1" (
    set "HASWARNING=1"
    echo [!] Claude / VM memory processes are RUNNING.
    echo     Quit Claude Desktop fully before moving the VM bundle.
    echo     Use tray icon -^> Quit if Claude is still in the notification area.
) else (
    echo [ok] No Claude / vmmem / vmmemWSL processes are running.
)

for %%P in (vmcompute.exe wslservice.exe wslhost.exe) do (
    tasklist /FI "IMAGENAME eq %%P" 2>nul | findstr /I "%%P" >nul
    if !errorlevel! equ 0 (
        echo [i] Virtualization / WSL service running: %%P  ^(may be normal^)
    )
)

REM ============================================================
REM 2. Check that the bundle exists and whether it is already moved
REM ============================================================
echo.
echo Step 2: Checking Claude VM bundle path...

if not exist "%SOURCE%" (
    set "HASWARNING=1"
    echo [!] Bundle path not found:
    echo     %SOURCE%
    echo.
    echo     Either Claude has not created the VM yet, the path changed, or it has already been moved.
    echo.
    echo Final result: NOT READY TO MOVE - source folder was not found.
    exit /b 1
)

REM Detect directory junction / reparse point.
fsutil reparsepoint query "%SOURCE%" >nul 2>&1
if !errorlevel! equ 0 (
    echo [i] Bundle path is already a junction/reparse point.
    echo     This usually means it has already been moved and linked.
) else (
    REM Calculate folder size in bytes.
    set "SIZEBYTES=0"
    for /f "tokens=3" %%S in ('dir /s /-c "%SOURCE%" 2^>nul ^| findstr /R /C:"[0-9] File(s)"') do set "SIZEBYTES=%%S"
    echo [ok] Real folder found. Total size: !SIZEBYTES! bytes
)

REM ============================================================
REM 3. Check whether VHDX files are locked
REM ============================================================
echo.
echo Step 3: Checking .vhdx file locks...

set "VHDXCOUNT=0"
set "LOCKEDCOUNT=0"
for /r "%SOURCE%" %%F in (*.vhdx) do (
    set /a VHDXCOUNT+=1
    REM Try to open the file for append (requires an exclusive-ish write handle).
    REM Succeeds only if no other process holds the file locked.
    2>nul ( >>"%%F" call ) && (
        echo [ok] Unlocked: %%~nxF
    ) || (
        set /a LOCKEDCOUNT+=1
        echo [!] LOCKED:   %%F
    )
)

if "!VHDXCOUNT!"=="0" (
    set "HASWARNING=1"
    echo [!] No .vhdx files found under the bundle path.
    echo     Path may be wrong, Claude changed its layout, or the bundle is incomplete.
) else (
    echo [i] Found !VHDXCOUNT! .vhdx file^(s^).
    if !LOCKEDCOUNT! gtr 0 (
        set "HASWARNING=1"
        echo     Quit Claude Desktop fully and re-run this check.
        echo     If still locked, reboot Windows and run this check before opening Claude.
    ) else (
        echo [ok] All .vhdx files are unlocked.
    )
)

REM ============================================================
REM 4. Final result
REM ============================================================
echo.
if "!HASWARNING!"=="1" (
    echo Final result: NOT READY / REVIEW WARNINGS ABOVE.
    echo Do not run move-claude-vm.bat until the lock warnings are gone.
    exit /b 1
) else (
    echo Final result: READY TO MOVE.
    echo When ready, run: move-claude-vm.bat
    exit /b 0
)
