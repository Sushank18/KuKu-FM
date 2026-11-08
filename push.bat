@echo off
setlocal

rem Check if a commit message was provided as an argument
if "%~1"=="" (
    for /f "tokens=1-4 delims=/ " %%a in ("%date%") do set mydate=%%a-%%b-%%c
    for /f "tokens=1-2 delims=: " %%a in ("%time%") do set mytime=%%a:%%b
    set "COMMIT_MSG=Auto-update: %mydate% %mytime%"
) else (
    set "COMMIT_MSG=%~1"
)

echo [1/3] Staging all changes...
git add .

echo [2/3] Committing with message: "%COMMIT_MSG%"...
git commit -m "%COMMIT_MSG%"

echo [3/3] Pushing to GitHub...
git push origin main

if %errorlevel% equ 0 (
    echo.
    echo ==============================================
    echo [SUCCESS] Everything successfully pushed to GitHub!
    echo ==============================================
) else (
    echo.
    echo [ERROR] Push failed. Check your internet connection or credentials.
)
