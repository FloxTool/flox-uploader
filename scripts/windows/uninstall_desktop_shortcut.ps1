# ============================================================
# Supprime le raccourci "Flox Uploader Dev" du Bureau.
# Sprint D.45 v0.5.0
# ============================================================

$desktop  = [Environment]::GetFolderPath('Desktop')
$shortcut = Join-Path $desktop 'Flox Uploader Dev.lnk'

if (-not (Test-Path $shortcut)) {
    Write-Host " Aucun raccourci a supprimer ($shortcut n'existe pas)."
    exit 0
}

Remove-Item -LiteralPath $shortcut -Force
Write-Host " Raccourci supprime du Bureau." -ForegroundColor Green
