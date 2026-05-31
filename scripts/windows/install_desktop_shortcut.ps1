# ============================================================
# Cree le raccourci "Flox Uploader Dev" sur le Bureau.
# Sprint D.45 v0.5.0
# ============================================================

$ErrorActionPreference = 'Stop'

$scriptDir = $PSScriptRoot
$toggleBat = Join-Path $scriptDir 'flox_toggle.bat'
$iconPath  = Join-Path $scriptDir 'flox_icon.ico'
$desktop   = [Environment]::GetFolderPath('Desktop')
$shortcut  = Join-Path $desktop 'Flox Uploader Dev.lnk'

if (-not (Test-Path $toggleBat)) {
    Write-Host "ERREUR : flox_toggle.bat introuvable : $toggleBat" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host " Installation du raccourci :"
Write-Host "   Cible    : $toggleBat"
Write-Host "   Icone    : $iconPath"
Write-Host "   Raccourci: $shortcut"
Write-Host ""

$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($shortcut)
$sc.TargetPath = $toggleBat
$sc.WorkingDirectory = $scriptDir
# WindowStyle 7 = Minimise (la fenetre cmd s'ouvre minimisee dans la barre des taches)
$sc.WindowStyle = 7
$sc.Description = 'Lance ou arrete le serveur Flox Uploader Dev (toggle)'
if (Test-Path $iconPath) {
    $sc.IconLocation = $iconPath
}
$sc.Save()

Write-Host " Raccourci cree sur le Bureau." -ForegroundColor Green
Write-Host ""
Write-Host " Double-clic dessus pour DEMARRER le serveur (ouvre le navigateur)."
Write-Host " Double-clic une 2e fois pour l'ARRETER."
Write-Host ""
