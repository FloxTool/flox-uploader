; ============================================================
; Inno Setup script — Flox Uploader
; ============================================================
; Genere un installeur Windows "FloxUploader-Setup-X.Y.Z.exe" qui :
;  - Installe dans %LOCALAPPDATA%\Programs\Flox Uploader\ (per-user, pas admin)
;  - Cree raccourci Menu Demarrer (toujours) + Bureau (optionnel)
;  - Propose de lancer l'app a la fin de l'install
;  - Desinstall propre via Panneau de configuration > "Ajout/Suppression"
;  - **Garde les data user** (%LOCALAPPDATA%\fremontlouis\flox-uploader\)
;    car elles vivent ailleurs que le dossier d'install
;
; Usage en CI :
;   ISCC.exe packaging\flox_uploader.iss /DMyAppVersion=0.3.5 /Qp
;
; Le binaire ISCC est pre-installe sur les runners GitHub Actions
; windows-latest dans "C:\Program Files (x86)\Inno Setup 6\ISCC.exe".
;
; Sprint 5g PLAN-V1.md.

#define MyAppName "Flox Uploader"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
#define MyAppPublisher "Flox"
#define MyAppURL "https://github.com/FloxTool/flox-uploader"
#define MyAppExeName "Flox Uploader.exe"

[Setup]
AppId={{8F6C5A8C-1234-4321-9876-ABCDEF123456}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
; Install per-user (pas admin) → DefaultDirName dans %LOCALAPPDATA%\Programs
; Cree par {autopf} qui resout automatiquement selon les privileges.
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
; Skip la page de "choix du repertoire" pour une UX plus fluide.
; L'user avance peut quand meme forcer un autre path via /DIR=... en ligne de commande.
DisableDirPage=yes
DisableProgramGroupPage=yes
; Per-user install : pas besoin de UAC
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
OutputDir=installer
OutputBaseFilename=FloxUploader-Setup-{#MyAppVersion}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
; UninstallDisplay : ce que le user voit dans "Ajout/Suppression de programmes"
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}
; Compatibility
MinVersion=10.0
; Icone du setup.exe lui-meme + des fenetres du wizard.
SetupIconFile=icon.ico
; Privacy : on ne reste pas en haut, pas plein ecran
WindowVisible=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Tout le bundle PyInstaller. Le path source est relatif au .iss
; (donc packaging/../dist/Flox Uploader/). En CI on lance ISCC depuis
; la racine du repo, donc le path est dist\Flox Uploader\*.
Source: "..\dist\Flox Uploader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Propose de lancer l'app a la fin de l'install (decochable).
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; A la desinstallation : on ne supprime PAS les data user.
; Les data vivent dans %LOCALAPPDATA%\fremontlouis\flox-uploader\
; (resolu par platformdirs.user_data_dir()), donc en dehors de {app}.
; Inno Setup supprime automatiquement {app} et son contenu, c'est tout
; ce qu'on veut.

[Code]
// Pas de logique custom necessaire pour la v1. On rajoutera ici plus tard
// si on veut un check pre-install ("ferme l'app si elle tourne", etc.).
