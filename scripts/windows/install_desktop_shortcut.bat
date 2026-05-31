@echo off
REM ============================================================
REM Installe un raccourci "Flox Uploader Dev" sur le Bureau.
REM Double-clic sur ce raccourci = toggle start/stop du serveur.
REM Sprint D.45 v0.5.0
REM
REM Implementation : delegue a install_desktop_shortcut.ps1
REM (evite les enfers d'echappement multi-ligne PowerShell dans cmd).
REM ============================================================
setlocal

set "SCRIPT_DIR=%~dp0"
set "PS1=%SCRIPT_DIR%install_desktop_shortcut.ps1"

if not exist "%PS1%" (
    echo ERREUR : install_desktop_shortcut.ps1 introuvable :
    echo   %PS1%
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
if errorlevel 1 (
    echo.
    echo  ERREUR : installation du raccourci echouee.
    pause
    exit /b 1
)

pause
exit /b 0
