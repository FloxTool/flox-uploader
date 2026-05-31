@echo off
REM ============================================================
REM Supprime le raccourci "Flox Uploader Dev" du Bureau.
REM Sprint D.45 v0.5.0
REM ============================================================
setlocal

set "SCRIPT_DIR=%~dp0"
set "PS1=%SCRIPT_DIR%uninstall_desktop_shortcut.ps1"

if not exist "%PS1%" (
    echo ERREUR : uninstall_desktop_shortcut.ps1 introuvable.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
timeout /T 2 >NUL
exit /b 0
