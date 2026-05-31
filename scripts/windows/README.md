# Raccourcis Windows pour Flox Uploader

## Raccourci bureau "Flox Uploader Dev" (Sprint D.45)

Un raccourci toggle pour démarrer/arrêter le serveur dev en un double-clic.

### Installation

Double-clique sur **`install_desktop_shortcut.bat`**. Un raccourci `Flox Uploader Dev`
apparaît sur ton Bureau avec l'icône Flox.

### Utilisation

- **Double-clic sur le raccourci → DÉMARRE** le serveur + ouvre `http://127.0.0.1:8765/` dans le navigateur
- **Double-clic à nouveau → ARRÊTE** le serveur (kill `flox-uploader.exe`)

Le script détecte automatiquement si le serveur tourne déjà via `tasklist`.

### Désinstallation

Double-clique sur **`uninstall_desktop_shortcut.bat`**. Le raccourci est supprimé
du Bureau.

### Fichiers

| Fichier | Rôle |
|---|---|
| `flox_toggle.bat` | Le script principal (toggle start/stop) |
| `flox_icon.ico` | Icône Flox multi-résolution (16/32/48/64/128/256 px) |
| `install_desktop_shortcut.bat` | Crée le raccourci sur le Bureau |
| `uninstall_desktop_shortcut.bat` | Supprime le raccourci |

### Personnalisation

Le port par défaut est `8765`. Pour le changer, édite la ligne `set "PORT=8765"`
dans `flox_toggle.bat`.

---

## Menu contextuel Inbox (legacy, peu utilisé)

`install_context_menu.bat` ajoute une entrée "Préparer avec Flox Uploader" dans
le menu contextuel Windows (clic-droit sur un fichier vidéo). Sprint pré-v0.5.0,
non maintenu activement.
