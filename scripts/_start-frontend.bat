@echo off
REM Frontend launcher invoked by start.bat in a fresh conhost window.
REM Kept in its own file to avoid quote-stripping issues with cmd /k.

if exist node_modules\.bin\vite.cmd goto run

echo [frontend] node_modules\.bin\vite.cmd missing - running npm install...
call npm install
if errorlevel 1 (
    echo.
    echo [frontend] npm install failed - not starting vite. See errors above.
    exit /b 1
)

:run
echo [frontend] starting vite dev server...
call npm run dev
