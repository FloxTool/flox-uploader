# Security Policy

## Versions supportées

| Version | Supportée |
|---|---|
| 0.3.x   | ✅ Oui |
| < 0.3   | ❌ Non |

Une fois la v0.4.0 publique sortie, seule la dernière release recevra des
correctifs de sécurité.

## Signaler une vulnérabilité

Si tu trouves une faille de sécurité dans Flox Uploader, **ne crée pas une
issue publique**. À la place :

1. Ouvre un **Security Advisory** privé sur GitHub :
   https://github.com/FloxTool/flox-uploader/security/advisories/new
2. Décris la faille avec autant de détails que possible (vecteur, impact,
   PoC si tu en as un)
3. J'accuse réception sous **7 jours**
4. Une correction sera publiée sous 30 jours pour les vulnérabilités
   critiques, sous 90 jours pour les autres

## Surface d'attaque connue

Flox Uploader est **local-first**. Le serveur web écoute par défaut sur
`127.0.0.1` (loopback) uniquement. Si tu actives l'exposition réseau
(prévu v0.5+), des considérations supplémentaires s'appliquent — voir la
doc à ce moment-là.

Les données sensibles stockées localement :
- Clés API TMDB / OMDb / tracker (dans `.env`)
- Passkey tracker (dans `.env`)
- Historique d'uploads (`jobs.db`)

Aucune de ces données ne quitte la machine sans appel API explicite vers
TMDB, OMDb ou le tracker configuré par l'utilisateur.

## Données utilisateur dans les logs et bug reports

Si tu ouvres un bug report avec un log attaché, **le `ScrubbingWriter`
intégré masque automatiquement les clés API et passkeys connues**. Mais
double-check toujours avant de partager. Aucun engagement n'est pris si
tu partages publiquement des données sensibles.
