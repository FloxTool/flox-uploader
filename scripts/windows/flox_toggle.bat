@echo off
REM ============================================================
REM Flox Uploader Dev - Toggle Start/Stop
REM Sprint D.45 v0.5.0
REM
REM Si le serveur tourne -> on l'arrete
REM Si le serveur est arrete -> on le demarre + on ouvre le navigateur
REM ============================================================
setlocal enabledelayedexpansion

REM ---- Chemin du repo (parent du dossier scripts/windows) ----
set "SCRIPT_DIR=%~dp0"
set "REPO_DIR=%SCRIPT_DIR%..\.."
pushd "%REPO_DIR%"
set "REPO_DIR=%CD%"
popd

set "VENV_EXE=%REPO_DIR%\.venv\Scripts\flox-uploader.exe"
set "PORT=8765"
set "URL=http://127.0.0.1:%PORT%/"

REM ---- Detecte si le serveur tourne ----
tasklist /FI "IMAGENAME eq flox-uploader.exe" 2>NUL | findstr /I "flox-uploader.exe" >NUL
if not errorlevel 1 (
    REM ====== STOP ======
    echo.
    echo  [Flox Uploader Dev] Arret du serveur...
    taskkill /F /IM flox-uploader.exe >NUL 2>&1
    if errorlevel 1 (
        echo  Erreur : impossible d'arreter le serveur.
        timeout /T 3 >NUL
        exit /b 1
    )
    echo  Serveur arrete.
    timeout /T 1 >NUL
    exit /b 0
)

REM ====== START ======
echo.
echo  [Flox Uploader Dev] Demarrage du serveur...

if not exist "%VENV_EXE%" (
    echo.
    echo  ERREUR : flox-uploader.exe introuvable :
    echo    %VENV_EXE%
    echo.
    echo  Verifie que le venv est cree et que 'pip install -e .[web,dev]' a ete fait.
    pause
    exit /b 1
)

REM Lance le serveur en background (fenetre minimisee, detachee)
start "Flox Uploader Dev" /MIN "%VENV_EXE%" serve

REM Attend que le serveur soit pret avant d'ouvrir le navigateur
echo  Demarrage en cours, ouverture du navigateur dans 3 secondes...
timeout /T 3 >NUL

start "" "%URL%"

echo  Serveur lance sur %URL%
echo.
echo  Re-lance ce raccourci pour arreter le serveur.
timeout /T 2 >NUL
exit /b 0
